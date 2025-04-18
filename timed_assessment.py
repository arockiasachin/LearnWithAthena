from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from datetime import datetime, timedelta
from models import Assignment, AssignmentSubmission, Student
from database import db_session
import os
from werkzeug.utils import secure_filename

timed_bp = Blueprint('timed', __name__, url_prefix='/timed')

@timed_bp.route('/start/<int:assignment_id>')
def start_assessment(assignment_id):
    """Initialize a new timed assessment"""
    if 'student_id' not in session:
        return redirect(url_for('auth.student_login'))
    
    assignment = db_session.get(Assignment, assignment_id)
    student = db_session.get(Student, session['student_id'])
    
    # Validate assessment access
    if not assignment or not assignment.is_published or not assignment.is_timed:
        flash('Invalid assessment', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    if not any(ss.subject_id == assignment.subject_id for ss in student.subject_associations):
        flash('Not enrolled in this subject', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    # Store assessment start time
    session['timed_assessment'] = {
        'assignment_id': assignment_id,
        'start_time': datetime.utcnow().isoformat(),
        'time_limit': assignment.time_limit_minutes
    }
    
    return redirect(url_for('timed.take_assessment', assignment_id=assignment_id))

@timed_bp.route('/take/<int:assignment_id>', methods=['GET', 'POST'])
def take_assessment(assignment_id):
    """Handle the assessment taking process"""
    if 'student_id' not in session or 'timed_assessment' not in session:
        return redirect(url_for('auth.student_login'))
    
    assessment_data = session['timed_assessment']
    if assessment_data['assignment_id'] != assignment_id:
        flash('Invalid assessment session', 'danger')
        return redirect(url_for('student.view_assignment'))
    
    assignment = db_session.get(Assignment, assignment_id)
    student = db_session.get(Student, session['student_id'])
    
    # Calculate remaining time
    start_time = datetime.fromisoformat(assessment_data['start_time'])
    elapsed = datetime.utcnow() - start_time
    remaining = timedelta(minutes=assessment_data['time_limit']) - elapsed
    remaining_seconds = max(0, remaining.total_seconds())
    
    # Handle submission
    if request.method == 'POST':
        if remaining_seconds <= 0:
            flash('Time has expired!', 'danger')
            return redirect(url_for('student.view_assignment'))
        
        # Create submission
        submission = AssignmentSubmission(
            assignment_id=assignment_id,
            student_id=student.id,
            content=request.form.get('content'),
            status='submitted'
        )
        
        # Handle file upload
        if file := request.files.get('file'):
            filename = secure_filename(file.filename)
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            submission.attachment_path = filename
        
        db_session.add(submission)
        db_session.commit()
        
        # Auto-grade if enabled
        if assignment.auto_grade:
            grade_assessment(submission)
        
        session.pop('timed_assessment', None)
        flash('Assessment submitted successfully!', 'success')
        return redirect(url_for('student.view_assignment', assignment_id=assignment_id))
    
    return render_template('student/timed_assessment.html',
                         assignment=assignment,
                         remaining_time=remaining_seconds)

def grade_assessment(submission):
    """Auto-grade the submission"""
    # Implement your grading logic
    content = submission.content or ""
    word_count = len(content.split())
    
    if word_count > 500:
        grade = 90
    elif word_count > 300:
        grade = 75
    elif word_count > 100:
        grade = 60
    else:
        grade = 50
    
    submission.grade = grade
    submission.status = 'graded'
    submission.graded_at = datetime.utcnow()
    db_session.commit()