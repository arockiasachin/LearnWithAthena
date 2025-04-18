from flask import request, session, redirect, url_for, flash, render_template
from models import Student
from database import db_session
from group_dashboard.utils import validate_step1_data

def formation_step1():
    if 'student_id' not in session:
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    if student.groups:
        return redirect(url_for('group.dashboard'))
    
    # Profile completion check
    if not student.profile_complete:
        flash('Complete your profile (register number and GitHub) before creating a group', 'danger')
        return redirect(url_for('student.update_profile'))
    
    if request.method == 'POST':
        group_name = request.form.get('name', '').strip()
        if not group_name:
            flash('Group name is required', 'danger')
        elif len(group_name) > 100:
            flash('Group name must be under 100 characters', 'danger')
        else:
            session['group'] = {'name': group_name}
            return redirect(url_for('group.formation.formation_step2'))
    
    return render_template('group/step1.html', step=1)