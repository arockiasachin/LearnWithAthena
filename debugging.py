from flask import Blueprint, render_template, session, redirect, url_for
from database import db_session
from models import DebuggingAssignment
from student_dashboard import get_existing_submission  
debugging_bp = Blueprint('debugging', __name__)

@debugging_bp.route('/assignment/<int:assignment_id>')
def view_debugging_assignment(assignment_id):
    if 'student_id' not in session:
        return redirect(url_for('auth.student_login'))
    
    assignment = db_session.get(DebuggingAssignment, assignment_id)
    if not assignment or not assignment.is_published:
        return redirect(url_for('student.view_assignments'))
    
    student = db_session.get(Student, session['student_id'])
    submission = get_existing_submission(assignment_id, student.id)
    
    return render_template('student/debugging_assessment.html',
                         assignment=assignment,
                         submission=submission)

@debugging_bp.route('/start/<int:assignment_id>')
def start_debugging(assignment_id):
    if 'student_id' not in session:
        return redirect(url_for('auth.student_login'))
    
    assignment = db_session.get(DebuggingAssignment, assignment_id)
    if not assignment:
        return redirect(url_for('student.view_assignments'))
    
    return render_template('student/debugging_assessment.html',
                         assignment=assignment)