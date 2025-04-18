from flask import request, session, redirect, url_for, flash, render_template
from models import Student, StudentSubject
from database import db_session
import logging

logger = logging.getLogger(__name__)

def formation_step2():
    try:
        if 'student_id' not in session:
            return redirect(url_for('auth.student_login'))
            
        student = db_session.get(Student, session['student_id'])
        if not student.profile_complete:
            flash('Complete your profile before adding members', 'danger')
            return redirect(url_for('student.update_profile'))
            
        if 'group' not in session:
            flash('Please complete step 1 first', 'warning')
            return redirect(url_for('group.formation.formation_step1'))
        
        # Get current student's subjects
        current_subjects = {s.subject_id for s in student.subject_associations}
        
        # Get students who share at least one subject with current student
        students = db_session.query(Student).join(StudentSubject).filter(
            Student.register_number != None,
            Student.github_username != None,
            Student.id != session['student_id'],  # Exclude current student
            StudentSubject.subject_id.in_(current_subjects)
        ).distinct().all()
        
        if request.method == 'POST':
            num_members = int(request.form.get('num_members', 0))
            members = []
            
            # Add selected members
            for i in range(1, num_members + 1):
                reg_num = request.form.get(f'member_{i}')
                if reg_num:
                    member = next((s for s in students if s.register_number == reg_num), None)
                    if member:
                        members.append(member.id)
            
            # Add current student as creator
            if session['student_id'] not in members:
                members.append(session['student_id'])
            
            if len(members) < 2:
                flash('You must have at least 2 members in your group', 'danger')
                return render_template('group/step2.html', 
                                    students=students,
                                    step=2)
            
            # Verify all members share at least one subject
            all_members = db_session.query(Student).filter(Student.id.in_(members)).all()
            common_subjects = None
            
            for member in all_members:
                member_subjects = {s.subject_id for s in member.subject_associations}
                if common_subjects is None:
                    common_subjects = member_subjects
                else:
                    common_subjects &= member_subjects
                
                if not common_subjects:
                    flash('All group members must share at least one common subject', 'danger')
                    return render_template('group/step2.html',
                                        students=students,
                                        step=2)
            
            session['members'] = members
            logger.info(f"Members added to session: {members}")
            return redirect(url_for('group.formation.formation_step3'))
        
        return render_template('group/step2.html',
                            students=students,
                            step=2)
    
    except Exception as e:
        logger.error(f"Step 2 Error: {str(e)}", exc_info=True)
        flash('An error occurred processing member data', 'danger')
        return redirect(url_for('group.formation.formation_step2'))