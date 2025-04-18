from flask import render_template, session, redirect, url_for, flash
from models import Student, Groups, Project
from database import db_session
from datetime import datetime

def dashboard():
    # Authentication check
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    # Get student and group info
    student = db_session.get(Student, session['student_id'])
    if not student.groups:
        return redirect(url_for('group.formation.formation_step1'))
    
    group = student.groups[0].group
    
    # Check if group has projects, create default if none
    if not group.projects:
        try:
            default_project = Project(
                group_id=group.group_id,
                name=f"{group.name}'s Project",
                description="Automatically created project",
                status='planning',
                created_at=datetime.utcnow()
            )
            db_session.add(default_project)
            db_session.commit()
            flash('A default project was created for your group', 'info')
            # Refresh the group object to include the new project
            group = db_session.get(Groups, group.group_id)
        except Exception as e:
            db_session.rollback()
            flash('Failed to create default project', 'danger')
    
    # Check if we should show timeline
    show_timeline = bool(group.projects and group.projects[0].tasks)
    
    return render_template('group/dashboard.html',
                         group=group,
                         timeline_div=show_timeline)