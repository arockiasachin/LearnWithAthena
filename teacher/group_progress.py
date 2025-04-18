from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from database import db_session
from models import Groups, Project, Task, TaskCommit, Student, StudentGroup, TaskAssignment
from sqlalchemy import func, case, and_, or_
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta
from . import teacher_bp
import logging

logger = logging.getLogger(__name__)

@teacher_bp.route('/group_progress')
def group_progress():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    # Get all groups with their projects and tasks
    groups = db_session.query(Groups).options(
        joinedload(Groups.projects).joinedload(Project.tasks),
        joinedload(Groups.members).joinedload(StudentGroup.student)
    ).all()
    
    # Calculate progress metrics for each group
    group_progress = []
    for group in groups:
        if not group.projects:
            continue
            
        project = group.projects[0]  # Assuming one project per group
        total_tasks = len(project.tasks)
        completed_tasks = sum(1 for t in project.tasks if t.status == 'Completed')
        
        # GitHub activity metrics
        commit_count = db_session.query(func.count(TaskCommit.id)).join(Task).filter(
            Task.project_id == project.project_id
        ).scalar()
        
        open_prs = sum(1 for t in project.tasks if t.pr_url and t.pr_state == 'open')
        
        group_progress.append({
            'group': group,
            'project': project,
            'progress': (completed_tasks / total_tasks * 100) if total_tasks else 0,
            'commit_count': commit_count,
            'open_prs': open_prs,
            'member_count': len(group.members)
        })
    
    return render_template('teacher/group_progress.html', 
                         group_progress=group_progress)

@teacher_bp.route('/group_detail/<int:group_id>')
def group_detail(group_id):
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    group = db_session.query(Groups).options(
        joinedload(Groups.projects).joinedload(Project.tasks),
        joinedload(Groups.members).joinedload(StudentGroup.student)
    ).get(group_id)
    
    if not group or not group.projects:
        flash('Group not found or has no project', 'danger')
        return redirect(url_for('teacher.group_progress'))
    
    project = group.projects[0]
    
    # Get date range filter
    time_period = request.args.get('time_period', 'all')
    now = datetime.utcnow()
    
    if time_period == 'week':
        start_date = now - timedelta(days=7)
    elif time_period == 'month':
        start_date = now - timedelta(days=30)
    else:
        start_date = None
    
    # Task progress calculation
    tasks = []
    for task in project.tasks:
        task_data = {
            'task': task,
            'assignees': [a.student for a in task.assignments],
            'commit_count': len(task.commits)
        }
        
        if start_date:
            task_data['recent_commits'] = [
                c for c in task.commits 
                if c.timestamp >= start_date
            ]
        else:
            task_data['recent_commits'] = task.commits
            
        tasks.append(task_data)
    
    # Member contribution analysis - updated to include GitHub no-reply emails
    # Member contribution analysis - updated to handle new GitHub email format
    member_contributions = []
    for member in group.members:
        student = member.student
        # Build query conditions for email matching
        conditions = [
            TaskCommit.author_email.ilike(student.email),
        ]
        
        # Add GitHub username conditions if available
        if student.github_username:
            # Handle both email formats: 
            # - 123456+username@users.noreply.github.com (new)
            # - username@users.noreply.github.com (old)
            conditions.append(
                TaskCommit.author_email.ilike(f"%{student.github_username}@users.noreply.github.com")
            )

        # Get all matching commits
        commits_query = db_session.query(TaskCommit).join(Task).filter(
            Task.project_id == project.project_id,
            or_(*conditions)
        )

        # Apply time filter if specified
        if start_date:
            commits_query = commits_query.filter(TaskCommit.timestamp >= start_date)

        commits = commits_query.all()

        # Calculate contribution metrics
        member_contributions.append({
            'student': student,
            'commit_count': len(commits),
            'lines_added': sum(c.additions for c in commits),
            'lines_deleted': sum(c.deletions for c in commits),
            'last_activity': max(c.timestamp for c in commits) if commits else None
        })
    
    return render_template('teacher/group_detail.html',
                         group=group,
                         project=project,
                         tasks=tasks,
                         member_contributions=member_contributions,
                         time_period=time_period)

@teacher_bp.route('/member_contributions/<int:group_id>/<int:student_id>')
def member_contributions(group_id, student_id):
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    group = db_session.get(Groups, group_id)
    student = db_session.get(Student, student_id)
    
    if not group or not student:
        flash('Group or student not found', 'danger')
        return redirect(url_for('teacher.group_progress'))
    
    if not group.projects:
        flash('Group has no project', 'danger')
        return redirect(url_for('teacher.group_progress'))
    
    project = group.projects[0]
    
    # Get all tasks assigned to this student
    assigned_tasks = db_session.query(Task).join(TaskAssignment).filter(
        TaskAssignment.student_id == student.id,
        Task.project_id == project.project_id
    ).all()
    
    # Get all commits by this student - updated to include GitHub no-reply emails
    commits = db_session.query(TaskCommit).join(Task).filter(
        Task.project_id == project.project_id,
        or_(
            TaskCommit.author_email == student.email,
            TaskCommit.author_email.like(f"%{student.github_username}@users.noreply.github.com")
        ) if student.github_username else TaskCommit.author_email == student.email
    ).order_by(TaskCommit.timestamp.desc()).all()
    
    # Calculate metrics
    completed_tasks = sum(1 for t in assigned_tasks if t.status == 'Completed')
    avg_progress = (sum(t.progress for t in assigned_tasks) / len(assigned_tasks)) if assigned_tasks else 0
    
    return render_template('teacher/member_contributions.html',
                         group=group,
                         student=student,
                         project=project,
                         assigned_tasks=assigned_tasks,
                         commits=commits,
                         completed_tasks=completed_tasks,
                         avg_progress=avg_progress)