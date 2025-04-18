from flask import render_template, session, redirect, url_for, flash, request
from models import Student, Project
from database import db_session
from datetime import datetime

def project_details():
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    if not student.groups:
        return redirect(url_for('group.formation.formation_step1'))
    
    group = student.groups[0].group
    
    # Create default project if none exists
    if not group.projects:
        default_project = Project(
            group_id=group.group_id,
            name=f"{group.name}'s Project",
            description="Automatically created project",
            status='planning'
        )
        db_session.add(default_project)
        try:
            db_session.commit()
            flash('A default project was created for your group', 'info')
        except Exception as e:
            db_session.rollback()
            flash('Failed to create default project', 'danger')
        return redirect(url_for('group.project_details'))
    
    # Handle project updates
    if request.method == 'POST':
        try:
            project = group.projects[0]
            project.name = request.form.get('name')
            project.description = request.form.get('description')
            project.tech_stack = ','.join(request.form.getlist('tech_stack'))
            project.milestones = request.form.get('milestones')
            project.status = request.form.get('status', 'planning')
            
            db_session.commit()
            flash('Project updated successfully', 'success')
        except Exception as e:
            db_session.rollback()
            flash(f'Error updating project: {str(e)}', 'danger')
        
        return redirect(url_for('group.project_details'))
    
    return render_template('group/project_details.html', group=group)