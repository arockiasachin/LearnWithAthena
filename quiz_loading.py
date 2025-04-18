# quiz_loading.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app,make_response
from models import QuizAttempt, Assignment,AssignmentSubmission,QuizSubmission
from database import db_session
import os
import pandas as pd
from datetime import datetime
import time
from student_dashboard import get_existing_submission
quiz_loading_bp = Blueprint('quiz_loading', __name__)

@quiz_loading_bp.route('/quiz/<int:attempt_id>')
def view_quiz(attempt_id):
    """Display the generated quiz with automatic redirect when ready"""
    attempt = db_session.get(QuizAttempt, attempt_id)
    if not attempt:
        flash('Quiz attempt not found', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    # If quiz is still generating, redirect back to loading page
    if attempt.status == 'generating':  # Note: Typo here, should be 'generating'
        return redirect(url_for('quiz_loading.quiz_generating', attempt_id=attempt_id))
    
    # Check if the quiz file exists with retry logic
    quiz_path = os.path.join(current_app.instance_path, 'quizzes', attempt.quiz_file)
    
    # Add retry mechanism for file reading
    max_retries = 3
    retry_delay = 0.5  # seconds
    
    for retry in range(max_retries):
        try:
            if not os.path.exists(quiz_path):
                if retry == max_retries - 1:  # Last attempt
                    flash('Quiz file not found', 'danger')
                    return redirect(url_for('student.view_assignment', assignment_id=attempt.assignment_id))
                time.sleep(retry_delay)
                continue
                
            # Read CSV with validation
            df = pd.read_csv(quiz_path)
            if df.empty:
                raise ValueError("Generated quiz file is empty")
                
            questions = df.to_dict('records')
            attempt.status = 'in_progress'
            db_session.commit()
            # Create response with cache control
            response = make_response(
                render_template('student/quiz_view.html',
                    questions=questions,
                    attempt=attempt,
                    assignment=attempt.quiz_assignment
                )
            )
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            
            return response
            
        except pd.errors.EmptyDataError:
            current_app.logger.error(f"Empty quiz file for attempt {attempt_id}")
            if retry == max_retries - 1:
                flash('Quiz content is invalid', 'danger')
                return redirect(url_for('student.view_assignment', assignment_id=attempt.assignment_id))
            time.sleep(retry_delay)
            
        except Exception as e:
            current_app.logger.error(f"Error reading quiz file (attempt {retry+1}): {str(e)}")
            if retry == max_retries - 1:
                flash('Error loading quiz questions', 'danger')
                return redirect(url_for('student.view_assignment', assignment_id=attempt.assignment_id))
            time.sleep(retry_delay)

@quiz_loading_bp.route('/quiz/submit/<int:attempt_id>', methods=['POST'])
def submit_quiz(attempt_id):
    """Handle quiz submission and grading"""
    attempt = db_session.get(QuizAttempt, attempt_id)
    if not attempt or attempt.status != 'in_progress':
        flash('Invalid quiz attempt', 'danger')
        return redirect(url_for('student.view_assignments'))

    try:
        # Get time left from form (default to 0 if not provided)
        time_left = int(request.form.get('time_left', 0))
        total_time = 600  # 10 minutes in seconds
        time_spent = max(0, total_time - time_left)

        # Read quiz questions and answers
        quiz_path = os.path.join(current_app.instance_path, 'quizzes', attempt.quiz_file)
        df = pd.read_csv(quiz_path)
        
        # Get correct answers with normalized IDs
        correct_answers = {}
        answer_column = 'Correct' if 'Correct' in df.columns else 'Answer'
        for _, row in df.iterrows():
            try:
                q_id = str(int(row['ID']))
                correct_answer = str(row[answer_column]).strip()
                correct_answers[q_id] = correct_answer
            except (KeyError, ValueError) as e:
                current_app.logger.error(f"Error processing question ID {row.get('ID')}: {str(e)}")
                continue

        # Process student answers with normalization
        student_answers = {}
        for key, value in request.form.items():
            if key.startswith('q'):
                try:
                    q_id = key[1:]  # Remove 'q' prefix
                    student_answers[q_id] = str(value).strip()
                except (IndexError, ValueError) as e:
                    current_app.logger.warning(f"Invalid answer key {key}: {str(e)}")

        # Remove non-answer fields
        student_answers.pop('time_left', None)
        student_answers.pop('csrf_token', None)

        # Grade answers with normalization
        correct_count = 0
        total_questions = len(correct_answers)
        
        def normalize_answer(answer: str) -> str:
            """Normalize answers for comparison"""
            return (
                answer.replace(' ', '')
                .replace('\\', '')
                .replace('$', '')
                .lower()
                .strip()
            )

        for q_id, student_answer in student_answers.items():
            correct_answer = correct_answers.get(q_id, '')
            if normalize_answer(student_answer) == normalize_answer(correct_answer):
                correct_count += 1
            else:
                current_app.logger.debug(
                    f"Mismatch Q{q_id}: Student '{student_answer}' vs Correct '{correct_answer}'"
                )

        # Calculate score as percentage of max points
        score = round((correct_count / total_questions) * attempt.assignment.max_points, 2) if total_questions > 0 else 0

        # Update attempt record
        attempt.answers = student_answers
        attempt.score = (correct_count / total_questions) * 100 if total_questions > 0 else 0  # Store percentage
        attempt.status = 'completed'
        attempt.submitted_at = datetime.utcnow()
        attempt.time_spent = time_spent
        attempt.results = {
            'total_questions': total_questions,
            'correct_answers': correct_count,
            'score': attempt.score,
            'time_spent': time_spent,
            'details': {
                'correct': list(correct_answers.keys()),
                'student': student_answers
            }
        }

        # Handle quiz submission record
        submission = get_existing_submission(attempt.assignment_id, attempt.student_id)
        if not submission:
            submission = QuizSubmission(
                assignment_id=attempt.assignment_id,
                student_id=attempt.student_id,
                content=str(attempt.results),
                status='graded',  # Mark as graded immediately
                grade=score,  # Store actual points earned
                submitted_at=datetime.utcnow(),
                quiz_data={
                    'attempt_id': attempt.id,
                    'time_spent': time_spent,
                    'version': attempt.version,
                    'raw_answers': student_answers,
                    'correct_answers': correct_answers
                }
            )
            db_session.add(submission)
        else:
            submission.content = str(attempt.results)
            submission.status = 'graded'
            submission.grade = score
            submission.submitted_at = datetime.utcnow()
            submission.quiz_data = {
                'attempt_id': attempt.id,
                'time_spent': time_spent,
                'version': attempt.version,
                'raw_answers': student_answers,
                'correct_answers': correct_answers
            }
            submission.attempt_number += 1

        db_session.commit()
        
        # Flash success message
        flash(f'Quiz submitted successfully! Your score: {score}/{attempt.assignment.max_points}', 'success')
        return redirect(url_for('quiz_loading.view_quiz_results', attempt_id=attempt_id))

    except Exception as e:
        db_session.rollback()
        current_app.logger.error(f"Error submitting quiz: {str(e)}", exc_info=True)
        flash('Error processing your quiz submission. Please contact support.', 'danger')
        return redirect(url_for('student.view_assignments'))

@quiz_loading_bp.route('/quiz/results/<int:attempt_id>')
def view_quiz_results(attempt_id):
    """Display quiz results to student"""
    attempt = db_session.get(QuizAttempt, attempt_id)
    if not attempt or attempt.status != 'completed':
        flash('Quiz results not available', 'danger')
        return redirect(url_for('student.view_assignments'))
    
    assignment = attempt.quiz_assignment
    submission = get_existing_submission(assignment.id, attempt.student_id)
    
    return render_template('student/quiz_results.html',
                         attempt=attempt,
                         assignment=assignment,
                         submission=submission)

@quiz_loading_bp.route('/quiz/generating/<int:attempt_id>')
def quiz_generating(attempt_id):
    """Show loading page while quiz is being generated"""
    attempt = db_session.get(QuizAttempt, attempt_id)
    if not attempt:
        flash('Quiz attempt not found', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    return render_template('student/quiz_generating.html', 
                         attempt=attempt,
                         assignment = attempt.quiz_assignment
)
    
@quiz_loading_bp.route('/api/quiz/status/<int:attempt_id>')
def quiz_status(attempt_id):
    """Check the status of a quiz generation attempt"""
    attempt = db_session.get(QuizAttempt, attempt_id)
    if not attempt:
        return {'status': 'failed', 'message': 'Quiz attempt not found'}, 404
    
    return {
        'status': attempt.status,
        'attempt_id': attempt.id,
        'assignment_id': attempt.assignment_id
    }