from flask import Blueprint, render_template, session, redirect, url_for, flash, current_app, request
from models import Assignment, AssignmentSubmission, Student,CodingSubmission,DescriptiveSubmission,QuizAttempt ,DebuggingSubmission
from database import db_session
from datetime import datetime
from sqlalchemy.orm import joinedload,with_polymorphic,selectin_polymorphic

marks_bp = Blueprint('marks', __name__)

@marks_bp.route('/marks')
def view_marks():
    if 'student_id' not in session:
        print('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    current_app.logger.info(f"Fetching marks for student ID: {session['student_id']}")
    
    # Get current time for comparison
    now = datetime.utcnow()
    current_app.logger.info(f"Current server time: {now}")
    
    # Get all submissions for this student
    submissions = db_session.query(AssignmentSubmission).join(
        Assignment,
        AssignmentSubmission.assignment_id == Assignment.id
    ).options(
        joinedload(AssignmentSubmission.assignment).joinedload(Assignment.subject)
    ).filter(
        AssignmentSubmission.student_id == student.id
    ).order_by(
        Assignment.due_date.desc(),
        AssignmentSubmission.status.desc()  # Show graded first
    ).all()
    
    current_app.logger.info(f"Found {len(submissions)} submissions:")
    for sub in submissions:
        current_app.logger.info(
            f"Submission ID: {sub.id} | "
            f"Assignment: {sub.assignment.title} | "
            f"Due: {sub.assignment.due_date} | "
            f"Status: {sub.status} | "
            f"Grade: {sub.grade}"
        )
    
    return render_template('student/marks.html',
                         submissions=submissions,
                         current_date=now.date())

@marks_bp.route('/marks/submission/<int:submission_id>')
def view_submission(submission_id):
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))

    try:
        # Load submission with polymorphism
        # Load submission with proper polymorphic configuration
        submission = (
                db_session.query(AssignmentSubmission)
                .options(
                    joinedload(AssignmentSubmission.assignment).joinedload(Assignment.subject),
                    joinedload(AssignmentSubmission.attachments),
                    selectin_polymorphic(
                        AssignmentSubmission, 
                        [CodingSubmission, DebuggingSubmission, DescriptiveSubmission, QuizAttempt]
                    )
                )
                .get(submission_id)
            )

        if not submission:
            flash('Submission not found', 'danger')
            return redirect(url_for('marks.view_marks'))
            
        if submission.student_id != session['student_id']:
            flash('Unauthorized access', 'danger')
            return redirect(url_for('marks.view_marks'))

        assignment_type = submission.assignment.assignment_type
        execution_results = None

        # Handle coding assignment specifics
        if assignment_type == 'Coding':
            # Check if this is actually a CodingSubmission
            if not isinstance(submission, CodingSubmission):
                flash('Coding submission details missing', 'danger')
                return redirect(url_for('marks.view_marks'))

            # Now safely access coding-specific fields
            test_results = submission.submission_data.get('test_results', {})
            stats = submission.submission_data.get('stats', {})
            
            execution_results = {
                'success': stats.get('success_rate', 0) == 1.0,
                'time_elapsed': submission.execution_metrics.get('max_time', 0),
                'memory_used': submission.execution_metrics.get('max_memory', 0),
                'error_message': next(
                    (t.get('error') for t in test_results.get('visible', []) 
                    if t.get('error')),
                    None
                ),
                'visible_tests': test_results.get('visible', []),
                'hidden_tests': test_results.get('hidden', []),
                'stats': stats
            }

        # Mark feedback as read if available
        if submission.feedback and not submission.feedback_read_at:
            try:
                submission.feedback_read_at = datetime.utcnow()
                db_session.commit()
            except Exception as e:
                db_session.rollback()
                current_app.logger.error(f"Failed to update feedback read time: {str(e)}")

        return render_template('student/view_submission.html',
                            submission=submission,
                            current_date=datetime.utcnow().date(),
                            execution_results=execution_results)

    except Exception as e:
        db_session.rollback()
        current_app.logger.error(f"Error viewing submission: {str(e)}", exc_info=True)
        flash('An error occurred while loading the submission', 'error')
        return redirect(url_for('marks.view_marks'))

    except Exception as e:
        db_session.rollback()
        current_app.logger.error(f"Error viewing submission: {str(e)}", exc_info=True)
        flash(e)
        flash('An error occurred while loading the submission', 'error')
        print('An error occurred while loading the submission', 'error')
        return redirect(url_for('marks.view_marks'))
    
@marks_bp.route('/marks/evaluate/<int:submission_id>', methods=['POST'])
def evaluate_submission(submission_id):
    if 'student_id' not in session and 'teacher_id' not in session and 'admin_id' not in session:
        print('Please log in first', 'danger')
        return redirect(url_for('auth.login'))

    submission = db_session.query(AssignmentSubmission)\
        .options(
            joinedload(AssignmentSubmission.assignment),
            joinedload(AssignmentSubmission.student)
        )\
        .get(submission_id)

    if not submission:
        print('Submission not found', 'danger')
        return redirect(url_for('marks.view_marks'))

    is_student_owner = 'student_id' in session and submission.student_id == session['student_id']
    is_teacher = 'teacher_id' in session
    is_admin = 'admin_id' in session

    if not (is_student_owner or is_teacher or is_admin):
        print('You are not authorized to evaluate this submission', 'danger')
        return redirect(url_for('marks.view_marks'))

    try:
        from descriptive_submission import evaluate_descriptive_submission
        evaluation_result = evaluate_descriptive_submission(
            assignment_title=submission.assignment.title,
            assignment_description=submission.assignment.description,
            student_response=submission.content or "",
            max_points=submission.assignment.max_points
        )

        submission.status = 'graded'
        submission.grade = evaluation_result['grade']
        submission.feedback = evaluation_result['feedback']
        submission.graded_at = datetime.utcnow()
        
        db_session.commit()
        print('Evaluation completed!', 'success')

    except Exception as e:
        db_session.rollback()
        current_app.logger.error(f"Evaluation failed: {str(e)}")
        print('Evaluation failed. Please try again later.', 'danger')

    return redirect(url_for('marks.view_submission', submission_id=submission_id))