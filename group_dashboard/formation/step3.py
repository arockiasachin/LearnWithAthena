from flask import request, session, redirect, url_for, flash, render_template
from models import Student, Groups, Project, StudentGroup
from database import db_session
import logging
from datetime import datetime
import secrets
import string
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

def generate_group_identifier():
    """Generate unique 8-character alphanumeric identifier"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(8))

def formation_step3():
    try:
        if 'student_id' not in session:
            return redirect(url_for('auth.student_login'))
            
        student = db_session.get(Student, session['student_id'])
        if not student.profile_complete:
            flash('Complete your profile before creating projects', 'danger')
            return redirect(url_for('student.update_profile'))
            
        if 'members' not in session or 'group' not in session:
            flash('Please complete previous steps first', 'warning')
            return redirect(url_for('group.formation.formation_step1'))

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            
            # Validate project data
            if not title or len(title) > 100:
                flash('Invalid project title', 'danger')
                return render_template('group/step3.html', step=3)
                
            if not description:
                flash('Project description is required', 'danger')
                return render_template('group/step3.html', step=3)

            try:
                # Generate unique group identifier
                group_identifier = generate_group_identifier()
                while db_session.query(Groups).filter_by(group_identifier=group_identifier).first():
                    group_identifier = generate_group_identifier()

                # Create and save group
                group = Groups(
                    group_identifier=group_identifier,
                    name=session['group']['name'],
                    description=f"Group for {title}",
                    created_at=datetime.utcnow(),
                    generation_method="student_created"
                )
                db_session.add(group)
                db_session.flush()  # Get group_id

                # Add members
                for member_id in session['members']:
                    role = 'creator' if member_id == session['student_id'] else 'member'
                    db_session.add(StudentGroup(
                        student_id=member_id,
                        group_id=group.group_id,
                        role=role
                    ))

                # Create project
                project = Project(
                    group_id=group.group_id,
                    name=title,
                    description=description,
                    status='planning',
                    created_at=datetime.utcnow()
                )
                db_session.add(project)
                
                db_session.commit()
                
                # Store group ID for step4 and clear temp data
                session['group_id'] = group.group_id
                for key in ['group', 'members', 'project']:
                    session.pop(key, None)
                
                return redirect(url_for('group.formation.formation_step4'))

            except IntegrityError as e:
                db_session.rollback()
                logger.error(f"Database error: {str(e)}")
                flash('Group creation failed. Please try again.', 'danger')
                return redirect(url_for('group.formation.formation_step3'))

        return render_template('group/step3.html', step=3)
        
    except Exception as e:
        logger.error(f"Step3 error: {str(e)}", exc_info=True)
        flash('An error occurred', 'danger')
        return redirect(url_for('group.formation.formation_step3'))