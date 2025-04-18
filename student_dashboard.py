from flask import Blueprint, render_template, session, redirect, url_for, flash, request,current_app
from models import Student, Subject,QuizAttempt, StudentSubject,AssignmentSubmission,CodingAssignment,DebuggingAssignment,QuizAssignment,DescriptiveAssignment
from database import db_session
from time_tracker import TimeTracker
from assessment_service import AssessmentService
from werkzeug.utils import secure_filename
import os
from sqlalchemy.orm import with_polymorphic, joinedload

student_bp = Blueprint('student', __name__)

@student_bp.route('/dashboard')
def student_dashboard():
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    
    # Check if student has a group to show appropriate navigation
    has_group = bool(student.groups)
    
    return render_template('student_dashboard.html',
                         student=student,
                         has_group=has_group)

# Context processor for student templates
@student_bp.context_processor
def inject_student_status():
    if 'student_id' in session:
        student = db_session.get(Student, session['student_id'])
        return {
            'has_group': bool(student.groups) if student else False,
            'current_student': student
        }
    return {'has_group': False, 'current_student': None}
# Add to student_dashboard.py
from models import Assignment, StudentSubject
from datetime import datetime

# Add to student_dashboard.py
@student_bp.route('/assignment/<int:assignment_id>/coding', methods=['GET', 'POST'])
def coding_assessment(assignment_id):
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    assignment = db_session.query(CodingAssignment).get(assignment_id)
    if not assignment or not assignment.is_published:
        flash('Assignment not found', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    # Check if student is enrolled
    student = db_session.get(Student, session['student_id'])
    if not any(ss.subject_id == assignment.subject_id for ss in student.subject_associations):
        flash('You are not enrolled in this subject', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    if request.method == 'POST':
        code = request.form.get('code')
        language = request.form.get('language')
        
        # Create submission
        submission = AssignmentSubmission(
            assignment_id=assignment_id,
            student_id=student.id,
            content=code,
            status='submitted',
            metadata={
                'language': language,
                'submitted_at': datetime.utcnow().isoformat()
            }
        )
        
        db_session.add(submission)
        db_session.commit()
        
        flash('Assignment submitted successfully!', 'success')
        return redirect(url_for('student.view_assignment', assignment_id=assignment_id))
    
    return render_template('student/assignments/coding_assessment.html', 
                         assignment=assignment,
                         remaining_time=assignment.time_limit_seconds)
    
@student_bp.route('/assignments')
def view_assignments():
    """
    Shows all published assignments for the subjects in which the student is enrolled.
    """
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    
    # Gather all subjects the student is enrolled in
    subject_ids = [ss.subject_id for ss in student.subject_associations]
    
    # Uncomment these two lines to debug your data in the console:
    # current_app.logger.debug("DEBUG subject_ids: %s", subject_ids)

    # Filter for published assignments that match any of the student's subjects
    assignments = db_session.query(Assignment).filter(
        Assignment.subject_id.in_(subject_ids),
        Assignment.is_published.is_(True)  # Replaced '== True' with '.is_(True)'
    ).order_by(Assignment.due_date).all()

    # Uncomment to debug the assignments fetched:
    # current_app.logger.debug("DEBUG assignments: %s", [(a.id, a.title, a.is_published) for a in assignments])
    return render_template(
        'student/assignments.html',
        assignments=assignments,
        current_date=datetime.utcnow().date()
    )
# In student_dashboard.py - Update view_quiz_assignment route
@student_bp.route('/assignment/quiz/<int:assignment_id>')
def view_quiz_assignment(assignment_id):
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    assignment = db_session.get(QuizAssignment, assignment_id)
    if not assignment or not assignment.is_published:
        flash('Assignment not found', 'danger')
        return redirect(url_for('student.view_assignments'))
    
    # Check enrollment
    student = db_session.get(Student, session['student_id'])
    if not any(ss.subject_id == assignment.subject_id for ss in student.subject_associations):
        flash('You are not enrolled in this subject', 'danger')
        return redirect(url_for('student.view_assignments'))
    
    submission = get_existing_submission(assignment_id, student.id)
    attempt = db_session.query(QuizAttempt).filter_by(
        assignment_id=assignment_id,
        student_id=student.id
    ).order_by(QuizAttempt.started_at.desc()).first()
    
    return render_template('student/assignments/quiz_assignment.html',
                         assignment=assignment,
                         submission=submission,
                         attempt=attempt,  # Add attempt to template context
                         current_date=datetime.utcnow().date())
    
# Add these new routes for type-specific views
@student_bp.route('/assignment/coding/<int:assignment_id>')
def view_coding_assignment(assignment_id):
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    assignment = get_coding_assignment(assignment_id)
    if not assignment or not assignment.is_published:
        flash('Assignment not found', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    student = db_session.get(Student, session['student_id'])
    submission = get_existing_submission(assignment_id, student.id)
    
    return render_template('student/assignments/coding_assessment.html',
                         assignment=assignment,
                         submission=submission,
                         current_date=datetime.utcnow().date())

@student_bp.route('/assignment/descriptive/<int:assignment_id>')
def view_descriptive_assignment(assignment_id):
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    assignment = get_descriptive_assignment(assignment_id)
    if not assignment or not assignment.is_published:
        flash('Assignment not found', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    student = db_session.get(Student, session['student_id'])
    submission = get_existing_submission(assignment_id, student.id)
    
    return render_template('student/assignments/descriptive_submission.html',
                         assignment=assignment,
                         submission=submission,
                         current_date=datetime.utcnow().date())

@student_bp.route('/assignment/<int:assignment_id>')
def view_assignment(assignment_id):
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))

    try:
        assignment = db_session.get(Assignment, assignment_id)
        if not assignment:
            flash('Assignment not found', 'danger')
            return redirect(url_for('student.view_assignments'))

        # Redirect to type-specific view
        if assignment.assignment_type == 'Coding':
            return redirect(url_for('student.view_coding_assignment', assignment_id=assignment_id))
        elif assignment.assignment_type == 'Descriptive':
            return redirect(url_for('student.view_descriptive_assignment', assignment_id=assignment_id))
        elif assignment.assignment_type == 'Quiz':
            return redirect(url_for('student.view_quiz_assignment', assignment_id=assignment_id))
        elif assignment.assignment_type == 'Debugging':
            return redirect(url_for('debugging.view_debugging_assignment', assignment_id=assignment_id))
        else:
            # Fallback for generic assignments
            student = db_session.get(Student, session['student_id'])
            submission = get_existing_submission(assignment_id, student.id)
            return render_template('student/assignment_base.html',
                                assignment=assignment,
                                submission=submission,
                                current_date=datetime.utcnow().date())

    except Exception as e:
        current_app.logger.error(f"Error loading assignment: {str(e)}")
        flash('Error loading assignment details', 'danger')
        return redirect(url_for('student.view_assignments'))
    
# student_dashboard.py (simplified version)
@student_bp.route('/assignment/<int:assignment_id>')
def view_assignmentq(assignment_id):
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))

    try:
        # Get base assignment
        assignment = db_session.get(Assignment, assignment_id)
        if not assignment:
            flash('Assignment not found', 'danger')
            return redirect(url_for('student.view_assignment'))

        # Load assignment type-specific data
        if assignment.assignment_type == 'Coding':
            assignment = get_coding_assignment(assignment_id)
        elif assignment.assignment_type == 'Debugging':
            assignment = get_debugging_assignment(assignment_id)
        elif assignment.assignment_type == 'Quiz':
            assignment = get_quiz_assignment(assignment_id)
        elif assignment.assignment_type == 'Descriptive':
            assignment = get_descriptive_assignment(assignment_id)
        else:
            flash('Unsupported assignment type', 'danger')
            return redirect(url_for('student.view_assignment'))

        if assignment.assignment_type == 'Coding':
            assignment = get_coding_assignment(assignment_id)
            if not assignment.time_limit_seconds:  # Verify attribute loading
                raise AttributeError("Coding assignment attributes not loaded properly")
        elif assignment.assignment_type == 'Debugging':
            assignment = get_debugging_assignment(assignment_id)
        
        # Common checks
        student = db_session.get(Student, session['student_id'])
        enrolled_subjects = [ss.subject_id for ss in student.subject_associations]
        if assignment.subject_id not in enrolled_subjects:
            flash('You are not enrolled in this subject', 'danger')
            return redirect(url_for('student.view_assignment'))

        submission = get_existing_submission(assignment_id, student.id)
        
        return render_template('student/assignment_base.html',
                            assignment=assignment,
                            submission=submission,
                            current_date=datetime.utcnow().date())

    except Exception as e:
        current_app.logger.error(f"Error loading assignment: {str(e)}")
        flash('Error loading assignment details', 'danger')
        return redirect(url_for('student.view_assignment'))

# Helper functions for specific assignment types
def get_coding_assignment(assignment_id):
    assignment = db_session.query(CodingAssignment).options(
        joinedload(CodingAssignment.attachments),
        joinedload(CodingAssignment.subject),
        joinedload(CodingAssignment.teacher)
    ).filter(CodingAssignment.id == assignment_id).one()
    
    # Set defaults if missing
    assignment.time_limit_seconds = assignment.time_limit_seconds or 3600
    assignment.memory_limit_mb = assignment.memory_limit_mb or 512
    assignment.language_options = assignment.language_options or ["python"]
    return assignment

def get_debugging_assignment(assignment_id):
    return db_session.query(DebuggingAssignment).options(
        joinedload(DebuggingAssignment.attachments),
        joinedload(DebuggingAssignment.subject),
        joinedload(DebuggingAssignment.teacher)
    ).get(assignment_id)

def get_quiz_assignment(assignment_id):
    return db_session.query(QuizAssignment).options(
        joinedload(QuizAssignment.attachments),
        joinedload(QuizAssignment.subject),
        joinedload(QuizAssignment.teacher)
    ).get(assignment_id)

def get_descriptive_assignment(assignment_id):
    return db_session.query(DescriptiveAssignment).options(
        joinedload(DescriptiveAssignment.attachments),
        joinedload(DescriptiveAssignment.subject),
        joinedload(DescriptiveAssignment.teacher)
    ).get(assignment_id)

def get_existing_submission(assignment_id, student_id):
    return db_session.query(AssignmentSubmission).filter_by(
        assignment_id=assignment_id,
        student_id=student_id
    ).first()

@student_bp.route('/assignment/<int:assignment_id>/submit', methods=['GET', 'POST'])
def submit_assignment(assignment_id):
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    assignment = db_session.get(Assignment, assignment_id)
    if not assignment or not assignment.is_published:
        flash('Assignment not found', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    # Check if assignment is past due
    if assignment.due_date < datetime.utcnow() and not assignment.allow_late_submissions:
        flash('This assignment is past due and no longer accepting submissions', 'danger')
        return redirect(url_for('student.view_assignment', assignment_id=assignment_id))
    
    # Check if student is enrolled in the subject
    student = db_session.get(Student, session['student_id'])
    if not any(ss.subject_id == assignment.subject_id for ss in student.subject_associations):
        flash('You are not enrolled in this subject', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    if request.method == 'POST':
        # Handle submission logic here
        content = request.form.get('content')
        file = request.files.get('file')
        
        try:
            # Create submission record
            submission = AssignmentSubmission(
                assignment_id=assignment_id,
                student_id=student.id,
                content=content,
                status='submitted'
            )
            
            # Handle file upload if present
            if file and file.filename:
                filename = secure_filename(file.filename)
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                submission.attachment_path = filename
            
            db_session.add(submission)
            db_session.commit()
            
            flash('Assignment submitted successfully!', 'success')
            return redirect(url_for('student.view_assignment', assignment_id=assignment_id))
            
        except Exception as e:
            db_session.rollback()
            flash(f'Error submitting assignment: {str(e)}', 'danger')
            print(f'Error submitting assignment: {str(e)}', 'danger')
            assignment = db_session.get(Assignment, assignment_id)
    
    return render_template('student/assignment_submit.html',
                         assignment=assignment,
                         current_date=datetime.utcnow().date())

@student_bp.route('/profile')
def view_profile():
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    return render_template('view_profile.html', current_student=student)

@student_bp.route('/profile/update', methods=['GET', 'POST'])
def update_profile():
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    all_subjects = db_session.query(Subject).filter_by(is_active=True).all()
    
    if request.method == 'POST':
        register_number = request.form.get('register_number')
        github_username = request.form.get('github_username')
        selected_subject_ids = request.form.getlist('enrolled_subjects')
        
        try:
            student.register_number = register_number
            student.github_username = github_username
            
            # Clear existing subjects
            db_session.query(StudentSubject).filter_by(student_id=student.id).delete()
            
            # Add new subjects with priority
            for priority, subject_id in enumerate(selected_subject_ids, start=1):
                if subject_id:
                    association = StudentSubject(
                        student_id=student.id,
                        subject_id=int(subject_id),
                        priority=priority  # Store the priority
                    )
                    db_session.add(association)
            
            db_session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('student.view_profile'))
        except Exception as e:
            db_session.rollback()
            flash(f'Error updating profile: {str(e)}', 'danger')
    
    return render_template('student_profile_update.html',
                         student=student,
                         all_subjects=all_subjects)