from flask import Blueprint, render_template, session, redirect, url_for, flash,request, current_app
from database import db_session
from models import Student, Groups, Project,CodingSubmission,CodingAssignment,DescriptiveSubmission,  Teacher, TeacherSubject, Subject, Assignment, AssignmentSubmission, StudentGroup
from . import teacher_bp
from sqlalchemy.orm import joinedload,selectin_polymorphic
from descriptive_submission import evaluate_descriptive_submission  # Add this import
from flask import request, flash, redirect, url_for
from datetime import datetime
from database import db_session
from models import AssignmentSubmission

@teacher_bp.route('/auto_grade', methods=['POST'])
def auto_grade():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))

    submission_id = request.form.get('submission_id')
    
    try:
        # Get base submission with polymorphic loading
        submission = db_session.query(AssignmentSubmission).options(
            selectin_polymorphic(AssignmentSubmission, [CodingSubmission, DescriptiveSubmission]),
            joinedload(AssignmentSubmission.assignment),
            joinedload(AssignmentSubmission.student)
        ).get(submission_id)

        if not submission:
            flash('Submission not found', 'danger')
            return redirect(url_for('teacher.student_monitoring'))

        # Handle Coding submissions
        if isinstance(submission, CodingSubmission):
            # Existing coding evaluation logic
            if not isinstance(submission.assignment, CodingAssignment):
                flash('Auto-grading only available for coding assignments', 'danger')
                return redirect(url_for('teacher.student_monitoring'))

            score_breakdown = submission.submission_data.get('score_breakdown', {})
            final_score_percent = score_breakdown.get('final', 0)
            max_points = submission.assignment.max_points
            calculated_grade = round((final_score_percent / 100) * max_points, 2)

        # Handle Descriptive submissions
        elif isinstance(submission, DescriptiveSubmission):
            evaluation_result = evaluate_descriptive_submission(
                assignment_title=submission.assignment.title,
                assignment_description=submission.assignment.description,
                student_response=submission.content,
                max_points=submission.assignment.max_points
            )
            
            calculated_grade = evaluation_result.get('grade')
            feedback = evaluation_result.get('feedback', 'Automatically graded using AI evaluation')
            
            if not calculated_grade:
                flash('Automatic evaluation failed', 'danger')
                return redirect(url_for('teacher.student_monitoring'))

            max_points = submission.assignment.max_points
            submission.feedback = feedback

        else:
            flash('Auto-grading not supported for this assignment type', 'danger')
            return redirect(url_for('teacher.student_monitoring'))

        # Common grading updates
        if calculated_grade < 0 or calculated_grade > max_points:
            flash('Invalid calculated grade', 'danger')
            return redirect(url_for('teacher.student_monitoring'))

        submission.grade = calculated_grade
        submission.graded_at = datetime.utcnow()
        submission.status = 'graded'

        db_session.commit()
        flash(f'Assignment graded: {calculated_grade}/{max_points}', 'success')

    except Exception as e:
        db_session.rollback()
        flash('Error during auto-grading', 'danger')
        current_app.logger.error(f"Auto-grade error: {str(e)}", exc_info=True)

    return redirect(url_for('teacher.student_monitoring'))

@teacher_bp.route('/force_grade', methods=['POST'])
def force_grade():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))

    try:
        submission_id = request.form['submission_id']
        submission = db_session.query(AssignmentSubmission).get(submission_id)
        
        if not submission:
            flash('Submission not found', 'danger')
            return redirect(url_for('teacher.student_monitoring'))

        # Validate grade input
        max_points = submission.assignment.max_points
        new_grade = float(request.form['grade'])
        
        if new_grade < 0 or new_grade > max_points:
            flash(f'Grade must be between 0 and {max_points}', 'danger')
            return redirect(url_for('teacher.student_monitoring'))

        # Update submission
        submission.grade = new_grade
        submission.feedback = request.form.get('feedback', '')
        submission.graded_at = datetime.utcnow()
        submission.status = 'graded'
        
        db_session.commit()
        flash('Grade updated successfully', 'success')

    except ValueError as e:
        db_session.rollback()
        flash('Invalid grade format - must be a number', 'danger')
        current_app.logger.error(f"Grade format error: {str(e)}")
    except Exception as e:
        db_session.rollback()
        flash('Error updating grade', 'danger')
        current_app.logger.error(f"Force grade error: {str(e)}")

    return redirect(url_for('teacher.student_monitoring'))

@teacher_bp.route('/student_monitoring')
def student_monitoring():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    try:
        # Eager load submissions and groups with their relationships
        students = db_session.query(Student).options(
            joinedload(Student.assignment_submissions).joinedload(AssignmentSubmission.assignment),
            joinedload(Student.groups).joinedload(StudentGroup.group)
        ).all()
        
        return render_template(
            'teacher/teacher_student_monitoring.html',
            students=students
        )
        
    except Exception as e:
        current_app.logger.error(f"Error loading student monitoring: {str(e)}")
        flash('Error loading student data', 'danger')
        return redirect(url_for('teacher.teacher_dashboard'))  # Changed from 'teacher.dashboard'