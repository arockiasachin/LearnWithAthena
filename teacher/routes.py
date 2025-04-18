from flask import render_template, session, redirect, url_for, flash, request
from . import teacher_bp
from database import db_session
from models import Teacher, Student, Groups, Project, TeacherSubject, Subject, Assignment

@teacher_bp.route('/dashboard')
def teacher_dashboard():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    teacher = db_session.get(Teacher, session['teacher_id'])
    
    total_students = db_session.query(Student).count()
    total_groups = db_session.query(Groups).count()
    active_projects = db_session.query(Project).filter(Project.status == 'active').count()
    
    teacher_subjects = db_session.query(Subject).join(TeacherSubject).filter(
        TeacherSubject.teacher_id == teacher.id
    ).all()
    
    recent_assignments = db_session.query(Assignment).filter(
        Assignment.teacher_id == teacher.id
    ).order_by(Assignment.due_date.desc()).limit(5).all()
    
    return render_template('teacher/teacher_dashboard.html',
                         teacher=teacher,
                         total_students=total_students,
                         total_groups=total_groups,
                         active_projects=active_projects,
                         teacher_subjects=teacher_subjects,
                         recent_assignments=recent_assignments)

@teacher_bp.route('/reports')
def reports():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    return render_template('teacher_reports.html')


@teacher_bp.route('/profile')
def view_profile():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    teacher = db_session.get(Teacher, session['teacher_id'])
    return render_template('teacher/teacher_view_profile.html', teacher=teacher)

@teacher_bp.route('/profile/update', methods=['GET', 'POST'])
def update_profile():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    teacher = db_session.get(Teacher, session['teacher_id'])
    all_subjects = db_session.query(Subject).filter_by(is_active=True).all()
    
    if request.method == 'POST':
        department = request.form.get('department')
        selected_subject_ids = request.form.getlist('assigned_subjects')
        
        try:
            teacher.department = department
            
            # Clear existing subject associations
            db_session.query(TeacherSubject).filter_by(teacher_id=teacher.id).delete()
            
            # Add new subject associations
            for subject_id in selected_subject_ids:
                if subject_id:
                    is_primary = request.form.get(f'is_primary_{subject_id}') == 'on'
                    association = TeacherSubject(
                        teacher_id=teacher.id,
                        subject_id=int(subject_id),
                        is_primary=is_primary
                    )
                    db_session.add(association)
            
            db_session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('teacher.view_profile'))
        except Exception as e:
            db_session.rollback()
            flash(f'Error updating profile: {str(e)}', 'danger')
    
    return render_template('teacher/teacher_profile_update.html',
                         teacher=teacher,
                         all_subjects=all_subjects)


@teacher_bp.context_processor
def inject_teacher_status():
    if 'teacher_id' in session:
        teacher = db_session.get(Teacher, session['teacher_id'])
        return {'current_teacher': teacher}
    return {'current_teacher': None}