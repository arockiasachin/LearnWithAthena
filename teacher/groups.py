from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from database import db_session
from models import Student, Groups, Project, Teacher, StudentGroup, StudentSubject, TeacherSubject, Subject, Assignment, FSLSMResult, AssignmentSubmission, QuizAttempt
from . import teacher_bp
from sqlalchemy import func, case
from sqlalchemy.orm import joinedload

@teacher_bp.route('/group_management')
def group_management():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    groups = db_session.query(Groups).options(
        joinedload(Groups.members).joinedload(StudentGroup.student)
    ).all()
    
    return render_template('teacher/teacher_group_management.html', groups=groups)



def create_fslsm_groups(subject_id, name_pattern, composition_type, group_size=4, activity_cycles=3):
    # VALIDATED QUERY - Gets ALL assignment types' grades
    # VALIDATED QUERY - Gets ALL assignment types' grades
    students = db_session.query(
        Student,
        func.coalesce(
            func.avg(
                case(
                    (AssignmentSubmission.grade.is_not(None), AssignmentSubmission.grade),
                    (QuizAttempt.score.is_not(None), QuizAttempt.score * 100),  # Normalize to 0-100 scale
                    else_=None  # Exclude nulls from average
                )
            ),
            0  # Default if no grades exist
        ).label('composite_score'),
        FSLSMResult.active_reflective,
        FSLSMResult.sensing_intuitive,
        FSLSMResult.visual_verbal,
        FSLSMResult.sequential_global
    ).join(
        StudentSubject, Student.id == StudentSubject.student_id
    ).join(
        FSLSMResult, Student.id == FSLSMResult.student_id
    ).outerjoin(
        AssignmentSubmission,
        (Student.id == AssignmentSubmission.student_id)
    ).outerjoin(
        Assignment,
        (AssignmentSubmission.assignment_id == Assignment.id) &
        (Assignment.subject_id == subject_id)
    ).outerjoin(
        QuizAttempt,
        (Student.id == QuizAttempt.student_id) &
        (QuizAttempt.assignment_id == Assignment.id)
    ).filter(
        StudentSubject.subject_id == subject_id,
        Student.fslsm_result != None
    ).group_by(
        Student.id, 
        FSLSMResult.id
    ).all()

    if not students:
        raise ValueError("No students with both FSLSM data and assignment submissions")

    # VALIDATED DATA STRUCTURE
    student_data = [{
        'id': s[0].id,
        'composite_score': s[1],
        'fslsm': {
            'active_reflective': s[2],
            'sensing_intuitive': s[3],
            'visual_verbal': s[4],
            'sequential_global': s[5]
        }
    } for s in students]

    # VALIDATED GROUPING LOGIC
    if composition_type == 'homogeneous':
        student_data.sort(key=lambda x: (
            x['fslsm']['active_reflective'],
            x['fslsm']['sensing_intuitive'],
            x['fslsm']['visual_verbal'],
            x['fslsm']['sequential_global']
        ))
    else:  # heterogeneous
        student_data.sort(key=lambda x: sum(
            abs(score) for score in [
                x['fslsm']['active_reflective'],
                x['fslsm']['sensing_intuitive'],
                x['fslsm']['visual_verbal'],
                x['fslsm']['sequential_global']
            ]
        ), reverse=True)

    # VALIDATED GROUP FORMATION
    groups = []
    for i in range(0, len(student_data), group_size):
        groups.append({
            'members': student_data[i:i+group_size],
            'activity_scores': []
        })

    # VALIDATED DYNAMIC ADJUSTMENT
    for _ in range(activity_cycles):
        for group in groups:
            # Calculate true average including all assignment types
            valid_scores = [m['composite_score'] for m in group['members'] if m['composite_score'] is not None]
            group_mean = sum(valid_scores)/len(valid_scores) if valid_scores else 0
            
            # Split and sort members
            above_avg = sorted(
                [m for m in group['members'] if m['composite_score'] >= group_mean],
                key=lambda x: x['composite_score'],
                reverse=True
            )
            below_avg = sorted(
                [m for m in group['members'] if m['composite_score'] < group_mean],
                key=lambda x: x['composite_score']
            )
            
            # Rebalance with style preservation
            merged = []
            for top, bottom in zip(above_avg, below_avg):
                merged.extend([top, bottom])
            
            # Handle remainder
            remainder = len(above_avg) - len(below_avg)
            if remainder > 0:
                merged.extend(above_avg[-remainder:])
            elif remainder < 0:
                merged.extend(below_avg[abs(remainder):])
            
            group['members'] = merged
            group['activity_scores'].append(group_mean)

    # VALIDATED DATABASE CREATION
    db_groups = []
    for i, group in enumerate(groups):
        db_group = Groups(
            name=name_pattern.replace('{n}', str(i+1)),
            group_identifier=f"FSLSM-{composition_type[:3].upper()}-{i+1:03d}",
            description=f"FSLSM {composition_type} group (v3) with {activity_cycles} cycles",
            generation_method=f"fslsm_{composition_type}_dynamic_full_aggregate"
        )
        db_session.add(db_group)
        
        for member in group['members']:
            db_session.add(StudentGroup(
                student_id=member['id'],
                group=db_group,
                role='member'
            ))
        
        db_groups.append(db_group)
    
    return db_groups

def create_performance_groups(subject_id, name_pattern, group_size):
    # Get students with average grades across ALL assignment types
    students = db_session.query(
        Student.id,
        func.coalesce(
            func.avg(AssignmentSubmission.grade),
            0
        ).label('avg_score')
    ).join(
        StudentSubject, Student.id == StudentSubject.student_id
    ).outerjoin(
        AssignmentSubmission,
        (Student.id == AssignmentSubmission.student_id) &
        (AssignmentSubmission.assignment_id == Assignment.id) &
        (Assignment.subject_id == subject_id)
    ).filter(
        StudentSubject.subject_id == subject_id
    ).group_by(Student.id).order_by(
        func.coalesce(func.avg(AssignmentSubmission.grade), 0).desc()
    ).all()

    # Convert to sorted student IDs with scores
    sorted_students = [s[0] for s in students]
    
    # Create balanced groups using sandwich approach
    balanced = []
    while sorted_students:
        # Take top performer
        if sorted_students:
            balanced.append(sorted_students.pop(0))
        # Take bottom performer
        if sorted_students:
            balanced.append(sorted_students.pop())
        # Take middle performer if odd number
        if sorted_students and len(sorted_students) % 2:
            balanced.append(sorted_students.pop(len(sorted_students)//2))

    return create_groups_from_sorted(balanced, name_pattern, group_size)

@teacher_bp.route('/create_groups', methods=['POST'])
def create_groups():
    if 'teacher_id' not in session:
        flash('Authentication required', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    group_type = request.form.get('group_type')
    subject_id = request.form.get('subject_id')
    name_pattern = request.form.get('name_pattern')
    
    try:
        if group_type == 'fslsm':
            groups = create_fslsm_groups(
                subject_id, 
                name_pattern,
                request.form.get('fslsm_type'),
                int(request.form.get('group_size', 4)),
                int(request.form.get('activity_cycles', 3))
            )
        elif group_type == 'performance':
            groups = create_performance_groups(
                subject_id, 
                name_pattern,
                int(request.form.get('group_size'))
            )
        elif group_type == 'self-registration':
            groups = create_self_registration_groups(subject_id, name_pattern)
        elif group_type == 'fslsm-dynamic':  # Fixed condition
            groups = create_fslsm_groups(
                subject_id,
                name_pattern,
                request.form.get('fslsm_dynamic_type'),  # Use dynamic-specific field
                int(request.form.get('dynamic_group_size')),  # Dynamic group size
                int(request.form.get('activity_cycles', 3))
            )
        else:
            flash('Invalid group type', 'danger')
            return redirect(url_for('teacher.group_management'))
        
        db_session.commit()
        print(groups)
        flash(f'Created {len(groups)} groups successfully', 'success')
        
    except Exception as e:
        db_session.rollback()
        flash(f'Error creating groups: {str(e)}', 'danger')
    
    return redirect(url_for('teacher.group_management'))

def create_dynamic_groups(subject_id, name_pattern, group_size=4, quiz_count=3):
    # Get students with quiz attempts for the subject
    students = db_session.query(
        Student,
        func.avg(QuizAttempt.score).label('avg_score')
    ).join(QuizAttempt).join(Assignment).join(Subject).filter(
        Subject.id == subject_id,
        QuizAttempt.score.isnot(None)
    ).group_by(Student.id).all()

    if not students:
        raise ValueError("No students with quiz scores found")

    # Convert to list of dictionaries with student and score
    student_data = [{
        'student': s[0],
        'score': s[1]
    } for s in students]

    # Sort students by average score
    sorted_students = sorted(student_data, key=lambda x: x['score'], reverse=True)
    
    # Calculate mean score
    scores = [s['score'] for s in sorted_students]
    mean = sum(scores) / len(scores)
    
    # Split into clusters
    greater_cluster = [s for s in sorted_students if s['score'] >= mean]
    smaller_cluster = [s for s in sorted_students if s['score'] < mean]
    
    # Sort clusters
    greater_sorted = sorted(greater_cluster, key=lambda x: x['score'], reverse=True)
    smaller_sorted = sorted(smaller_cluster, key=lambda x: x['score'])
    
    # Merge clusters alternately
    merged = []
    for g, s in zip(greater_sorted, smaller_sorted):
        merged.extend([g, s])
    
    # Add remaining students
    remaining = len(greater_sorted) - len(smaller_sorted)
    if remaining > 0:
        merged.extend(greater_sorted[-remaining:])
    elif remaining < 0:
        merged.extend(smaller_sorted[-abs(remaining):])
    
    # Extract student IDs in merged order
    student_ids = [s['student'].id for s in merged]
    
    return create_groups_from_sorted(student_ids, name_pattern, group_size)

def create_self_registration_groups(subject_id, name_pattern):
    # Create empty groups for self-registration
    groups = []
    for i in range(1, 6):  # Create 5 empty groups
        group = Groups(
            name=name_pattern.replace('{n}', str(i)),
            group_identifier=f"SR-{Subject.query.get(subject_id).code}-{i}",
            description="Self-registration group"
        )
        db_session.add(group)
        groups.append(group)
    return groups

def create_groups_from_sorted(student_ids, name_pattern, group_size):
    groups = []
    for i in range(0, len(student_ids), group_size):
        group = Groups(
            name=name_pattern.replace('{n}', str(len(groups)+1)),
            group_identifier=f"GRP-{len(groups)+1:03d}",
            description=f"Auto-generated group {len(groups)+1}"
        )
        db_session.add(group)
        
        for student_id in student_ids[i:i+group_size]:
            db_session.add(StudentGroup(
                student_id=student_id,
                group=group,
                role='member'
            ))
        
        groups.append(group)
        print(groups)
    return groups

@teacher_bp.route('/edit_group/<int:group_id>', methods=['GET', 'POST'])
def edit_group(group_id):
    if 'teacher_id' not in session:
        flash('Authentication required', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    group = db_session.get(Groups, group_id)
    if not group:
        flash('Group not found', 'danger')
        return redirect(url_for('teacher.group_management'))
    
    if request.method == 'POST':
        try:
            group.name = request.form.get('name')
            group.description = request.form.get('description')
            db_session.commit()
            flash('Group updated successfully', 'success')
            return redirect(url_for('teacher.group_management'))
        except Exception as e:
            db_session.rollback()
            flash(f'Error updating group: {str(e)}', 'danger')
    
    return render_template('teacher/edit_group.html', group=group)

@teacher_bp.route('/delete_group/<int:group_id>', methods=['POST'])
def delete_group(group_id):
    if 'teacher_id' not in session:
        flash('Authentication required', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    group = db_session.get(Groups, group_id)
    if not group:
        flash('Group not found', 'danger')
        return redirect(url_for('teacher.group_management'))
    
    try:
        db_session.delete(group)
        db_session.commit()
        flash('Group deleted successfully', 'success')
    except Exception as e:
        db_session.rollback()
        flash(f'Error deleting group: {str(e)}', 'danger')
    
    return redirect(url_for('teacher.group_management'))

@teacher_bp.route('/manage_members/<int:group_id>', methods=['GET', 'POST'])
def manage_members(group_id):
    if 'teacher_id' not in session:
        flash('Authentication required', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    group = db_session.get(Groups, group_id)
    if not group:
        flash('Group not found', 'danger')
        return redirect(url_for('teacher.group_management'))
    
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        action = request.form.get('action')
        
        student = db_session.get(Student, student_id)
        if not student:
            flash('Student not found', 'danger')
            return redirect(url_for('teacher.manage_members', group_id=group_id))
        
        if action == 'add':
            if not any(m.student_id == student.id for m in group.members):
                new_member = StudentGroup(student_id=student.id, group_id=group.group_id)
                db_session.add(new_member)
                flash('Student added to group', 'success')
        elif action == 'remove':
            member = next((m for m in group.members if m.student_id == student.id), None)
            if member:
                db_session.delete(member)
                flash('Student removed from group', 'success')
        
        db_session.commit()
    
    # Get students not in the group
    all_students = db_session.query(Student).all()
    non_members = [s for s in all_students if not any(m.student_id == s.id for m in group.members)]
    
    return render_template(
        'teacher/manage_members.html',
        group=group,
        non_members=non_members
    )