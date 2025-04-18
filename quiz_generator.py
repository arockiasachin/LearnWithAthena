# quiz_generator.py
import os
import ast
from datetime import datetime
from flask import Flask, redirect, url_for, session, flash, render_template, request, current_app, send_from_directory
from models import Assignment, Student, QuizAttempt
from student_dashboard import student_bp
import pandas as pd
from threading import Thread
from database import db_session
import signal
from functools import wraps
import time

# Security Note: Move this to environment variables in production
os.environ["DEEPSEEK_API_KEY"] = "API KEY"

# Import necessary functions from your notebook
from quiz_functions import (
    quiz_metadata_chain,
    question_expansion_chain,
    retrieval_chain,
    compression_retrieverv2,
    jina_embeddings
)

def with_app_context(app):
    """Decorator to ensure function runs with application context"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            with app.app_context():
                return f(*args, **kwargs)
        return wrapper
    return decorator

def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

@student_bp.route('/assignment/<int:assignment_id>/generate_quiz', methods=['POST'])
def generate_quiz(assignment_id):
    """Generate a practice quiz CSV from the assignment content."""
    # Authentication check
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    # Assignment validation
    assignment = db_session.get(Assignment, assignment_id)
    if not assignment:
        flash('Assignment not found', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    if not assignment.is_published:
        flash('This assignment is not currently available', 'warning')
        return redirect(url_for('student.view_assignment'))

    # Enrollment check
    student = db_session.get(Student, session['student_id'])
    if not any(ss.subject_id == assignment.subject_id for ss in student.subject_associations):
        flash('You are not enrolled in this subject', 'danger')
        return redirect(url_for('student.view_assignment'))

    try:
        # Create the QuizAttempt record first with 'generating' status
        attempt = QuizAttempt(
        student_id=student.id,
        assignment_id=assignment.id,  # Match foreign key name
        started_at=datetime.utcnow(),  # Use existing started_at field
        quiz_file="",
        status='generating',
        progress="0% - Initializing"
    )
        db_session.add(attempt)
        db_session.commit()
        
        # Start background task with app context
        app = current_app._get_current_object()
        Thread(
            target=generate_quiz_background,
            args=(app, attempt.id)
        ).start()
        
        return redirect(url_for('quiz_loading.quiz_generating', attempt_id=attempt.id))

    except Exception as e:
        db_session.rollback()
        current_app.logger.error(f"Error initiating quiz generation: {str(e)}")
        flash('Failed to start quiz generation', 'danger')
        return redirect(url_for('student.view_assignment', assignment_id=assignment_id))

def generate_quiz_background(app, attempt_id):
    """Background task that generates the quiz with proper session handling and timeout"""
    with app.app_context():
        # Create a new database session for this thread
        from database import SessionLocal
        thread_db_session = SessionLocal()
        attempt = thread_db_session.get(QuizAttempt, attempt_id)
        
        if not attempt:
            app.logger.error(f"Quiz attempt {attempt_id} not found")
            return

        try:
            # Initialize timeout tracking (Windows-compatible)
            start_time = time.time()
            timeout = 300  # 5 minutes in seconds
            
            # Step 1: Prepare quiz metadata
            assignment = attempt.quiz_assignment
            student = attempt.student
            quiz_metadata = {
                "title": assignment.title,
                "description": assignment.description,
                "subject": assignment.subject.name,
                "due_date": assignment.due_date.strftime('%Y-%m-%d')
            }
            
            # Update progress
            attempt.progress = "10% - Preparing metadata"
            thread_db_session.commit()

            # Check timeout
            if time.time() - start_time > timeout:
                raise TimeoutError("Quiz generation timed out")

            # Step 2: Expand questions with metadata
            result = expand_questions_with_metadata({
                "quiz_description": f"{quiz_metadata['title']}: {quiz_metadata['description']}",
                "subject": quiz_metadata['subject']
            })
            
            if not result or 'expanded_questions' not in result:
                raise ValueError("Failed to generate quiz questions")

            # Update progress
            attempt.progress = "25% - Expanding questions"
            thread_db_session.commit()

            # Step 3: Retrieve relevant documents
            question_list = ast.literal_eval(result['expanded_questions'])
            all_retrieved_docs = []
            
            for i, question in enumerate(question_list):
                # Check timeout periodically
                if time.time() - start_time > timeout:
                    raise TimeoutError("Quiz generation timed out")
                
                try:
                    retrieved_docs = compression_retrieverv2.invoke(question)
                    if retrieved_docs:
                        all_retrieved_docs.extend(retrieved_docs)
                    
                    # Update progress every few questions
                    if i % 2 == 0:
                        attempt.progress = f"30% - Retrieving documents ({i+1}/{len(question_list)})"
                        thread_db_session.commit()
                except Exception as e:
                    app.logger.warning(f"Error retrieving documents for question: {str(e)}")
                    continue

            if not all_retrieved_docs:
                raise ValueError("No relevant content found for quiz generation")

            # Step 4: Generate MCQs
            document_contents = [doc.page_content for doc in all_retrieved_docs]
            topics = ast.literal_eval(result['topics'])
            number_of_questions = result.get('number', 10)
            
            attempt.progress = "60% - Generating questions"
            thread_db_session.commit()

            mcq_result = retrieval_chain.invoke({
                "topics": topics,
                "Number": number_of_questions,
                "context": document_contents
            })

            if not mcq_result or 'response' not in mcq_result:
                raise ValueError("Failed to generate MCQ content")

            # Step 5: Process CSV output
            output_text = mcq_result['response']
            start_marker = "```csv\n"
            end_marker = "```"
            
            if start_marker not in output_text or end_marker not in output_text:
                raise ValueError("Invalid quiz format generated")

            start_idx = output_text.find(start_marker) + len(start_marker)
            end_idx = output_text.find(end_marker, start_idx)
            csv_data = output_text[start_idx:end_idx].strip()

            # Step 6: Save to CSV
            quizzes_dir = os.path.join(app.instance_path, 'quizzes')
            os.makedirs(quizzes_dir, exist_ok=True)
            
            clean_title = ''.join(c if c.isalnum() else '_' for c in assignment.title)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"quiz_{clean_title}_{assignment.id}_{timestamp}.csv"
            filepath = os.path.join(quizzes_dir, filename)
            
            try:
                with open(filepath, 'w', newline='', encoding='utf-8') as f:
                    f.write(csv_data)
            except IOError as e:
                raise ValueError(f"Failed to save quiz file: {str(e)}")
            
            
            # Check for existing generated quizzes
            existing_attempts = thread_db_session.query(QuizAttempt).filter(
                QuizAttempt.assignment_id == attempt.assignment_id,
                QuizAttempt.student_id == attempt.student_id,
                QuizAttempt.status.in_(['ready', 'completed'])
            ).all()
            
            # Archive old attempts
            for old_attempt in existing_attempts:
                old_attempt.status = 'archived'
                old_attempt.progress = 'Replaced by new attempt'
            
            # Proceed with generation
            assignment = attempt.quiz_assignment
            quiz_metadata = {
                "title": assignment.title,
                "description": assignment.description,
                "subject": assignment.subject.name
            }

            # Final update
            attempt.quiz_file = filename
            attempt.status = 'ready'
            attempt.questions_count = number_of_questions
            attempt.version = len(existing_attempts) + 1
            attempt.topics = str(topics)
            attempt.progress = "100% - Completed"
            thread_db_session.commit()

            app.logger.info(f"Successfully generated quiz for attempt {attempt_id}")
            time.sleep(10)

        except TimeoutError:
            thread_db_session.rollback()
            attempt.status = 'failed'
            attempt.progress = 'timed out'
            thread_db_session.commit()
            app.logger.error(f"Quiz generation timed out for attempt {attempt_id}")
            
        except Exception as e:
            thread_db_session.rollback()
            attempt.status = 'failed'
            attempt.progress = f'failed: {str(e)[:100]}'  # Truncate long error messages
            thread_db_session.commit()
            app.logger.error(f"Error generating quiz: {str(e)}", exc_info=True)
            
        finally:
            thread_db_session.close()  # Clean up the session

@student_bp.route('/quiz/download/<int:attempt_id>')
def download_quiz(attempt_id):
    attempt = db_session.get(QuizAttempt, attempt_id)
    if not attempt:
        flash('Quiz attempt not found', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    quizzes_dir = os.path.join(current_app.instance_path, 'quizzes')
    return send_from_directory(
        directory=quizzes_dir,
        path=attempt.quiz_file,
        as_attachment=True,
        download_name=f"Quiz_{attempt.assignment.title}.csv"
    )

def expand_questions_with_metadata(input_data):
    """Wrapper function for the question expansion chain"""
    topics_response = quiz_metadata_chain.invoke({
        "quiz_description": input_data["quiz_description"]
    })
    
    lines = topics_response.strip().split('\n')
    number = lines[0].strip() if len(lines) > 0 else ""
    topics = lines[1].strip() if len(lines) > 1 else ""
    
    expanded_questions = question_expansion_chain.invoke({
        "topics": topics,
        "number": number
    })
    
    return {
        "quiz_description": input_data["quiz_description"],
        "number": number,
        "topics": topics,
        "expanded_questions": expanded_questions
    }