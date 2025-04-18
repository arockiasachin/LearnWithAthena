
from flask import render_template, session, redirect, url_for, flash
from models import Student
from database import db_session

def member_details():
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    if not student.groups:
        return redirect(url_for('group.formation_step1'))
    
    group = student.groups[0].group
    return render_template('group/member_details.html', group=group)