from flask import render_template, session, redirect, url_for, flash, request, current_app
from models import Student, Task, Project, TaskAssignment, TaskDependency
from database import db_session
from datetime import datetime
import pandas as pd
import logging
import re
import io
import csv
from group_dashboard.github_integration import GitHubIntegration
from group_dashboard.github_utils import decrypt_token

logger = logging.getLogger(__name__)

def validate_branch_name(name):
    """Convert task name to valid GitHub branch name with debug logging"""
    logger.debug(f"Validating branch name from: {name}")
    cleaned = re.sub(r'[^\w\-]', '', name.lower().replace(' ', '-'))[:40]
    logger.debug(f"Cleaned branch name: {cleaned}")
    return cleaned

def project_timeline():
    """Main timeline view with enhanced debug logging"""
    logger.info("Entering project_timeline view")
    
    # Authentication and group check
    if 'student_id' not in session:
        logger.warning("Unauthenticated access attempt to timeline")
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    if not student.groups:
        logger.warning(f"Student {student.id} attempted timeline without group")
        flash('You need to join a group first', 'warning')
        return redirect(url_for('group.formation.formation_step1'))
    
    group = student.groups[0].group
    logger.debug(f"Processing timeline for group {group.group_id}")

    # Get or create project with error handling
    try:
        if not group.projects:
            logger.info("No projects found, creating default")
            default_project = Project(
                group_id=group.group_id,
                name=f"{group.name}'s Project",
                description="Automatically created project",
                status='planning'
            )
            db_session.add(default_project)
            db_session.commit()
            flash('A default project was created for your group', 'info')
            logger.info(f"Created default project {default_project.project_id}")
    except Exception as e:
        db_session.rollback()
        logger.error(f"Project creation failed: {str(e)}", exc_info=True)
        flash('Failed to initialize project', 'danger')
        return redirect(url_for('group.dashboard'))

    project = group.projects[0]
    logger.debug(f"Using project {project.project_id}")

    # Handle form submissions
    if request.method == 'POST':
        logger.info("Processing POST request to timeline")
        
        # CSV Import
        if 'csv_file' in request.files:
            logger.info("Processing CSV import")
            csv_file = request.files['csv_file']
            if csv_file.filename.endswith('.csv'):
                try:
                    logger.debug(f"Processing CSV file: {csv_file.filename}")
                    stream = io.StringIO(csv_file.stream.read().decode("UTF8"), newline=None)
                    csv_reader = csv.DictReader(stream)
                    
                    required_columns = ['Task Name', 'Start Date', 'Due Date', 'Assigned Emails']
                    if not all(col in csv_reader.fieldnames for col in required_columns):
                        logger.error(f"Missing required columns in CSV: {csv_reader.fieldnames}")
                        flash('CSV missing required columns', 'danger')
                        return redirect(url_for('group.project_timeline'))
                    
                    task_name_to_id = {}
                    imported_tasks = []
                    
                    for row in csv_reader:
                        try:
                            logger.debug(f"Processing row {csv_reader.line_num}: {row}")
                            task_name = row['Task Name']
                            start_date = datetime.strptime(row['Start Date'], '%Y-%m-%d')
                            due_date = datetime.strptime(row['Due Date'], '%Y-%m-%d')
                            
                            if start_date > due_date:
                                logger.warning(f"Invalid dates in row {csv_reader.line_num}")
                                flash(f'Invalid dates in row {csv_reader.line_num}: Start date after due date', 'warning')
                                continue
                            
                            new_task = Task(
                                project_id=project.project_id,
                                name=task_name,
                                start_date=start_date,
                                due_date=due_date,
                                status=row.get('Status', 'Not Started'),
                                progress=max(0, min(100, int(row.get('Progress', 0)))),
                                description=row.get('Description', ''),
                                objectives=[o.strip() for o in row.get('Objectives', '').split(';') if o.strip()],
                                outcomes=[o.strip() for o in row.get('Outcomes', '').split(';') if o.strip()],
                            )
                            db_session.add(new_task)
                            db_session.flush()
                            
                            branch_name = f"task-{new_task.task_id}-{validate_branch_name(task_name)}"
                            new_task.github_branch = branch_name
                            logger.debug(f"Created task {new_task.task_id} with branch {branch_name}")
                            
                            task_name_to_id[task_name] = new_task.task_id
                            imported_tasks.append(new_task)
                            
                            emails = [e.strip() for e in row['Assigned Emails'].split(',') if e.strip()]
                            for email in emails:
                                student = db_session.query(Student).filter_by(email=email).first()
                                if student:
                                    db_session.add(TaskAssignment(
                                        task_id=new_task.task_id,
                                        student_id=student.id
                                    ))
                                    logger.debug(f"Assigned task {new_task.task_id} to {email}")
                        
                        except Exception as e:
                            db_session.rollback()
                            logger.error(f"Error processing CSV row {csv_reader.line_num}: {str(e)}", exc_info=True)
                            flash(f'Error in row {csv_reader.line_num}: {str(e)}', 'warning')
                            continue
                    
                    # Handle dependencies
                    stream.seek(0)
                    csv_reader = csv.DictReader(stream)
                    
                    for row in csv_reader:
                        try:
                            task_name = row['Task Name']
                            if task_name not in task_name_to_id:
                                continue
                                
                            if row.get('Dependencies'):
                                dep_names = [n.strip() for n in row['Dependencies'].split(',') if n.strip()]
                                for dep_name in dep_names:
                                    if dep_name in task_name_to_id:
                                        db_session.add(TaskDependency(
                                            task_id=task_name_to_id[task_name],
                                            depends_on_id=task_name_to_id[dep_name]
                                        ))
                                        logger.debug(f"Added dependency: {task_name} -> {dep_name}")
                                    else:
                                        logger.warning(f"Dependency {dep_name} not found for {task_name}")
                                        flash(f'Dependency "{dep_name}" not found for task "{task_name}"', 'warning')
                        except Exception as e:
                            db_session.rollback()
                            logger.error(f"Error processing dependencies for {task_name}: {str(e)}")
                            flash(f'Error processing dependencies for {task_name}: {str(e)}', 'warning')
                            continue
                    
                    # GitHub branch creation
                    if group.repo_details:
                        logger.info("Attempting GitHub branch creation")
                        try:
                            logger.debug(f"Repo details: {group.repo_details.github_repo_url}")
                            logger.debug("Decrypting access token...")
                            github = GitHubIntegration.get_authenticated_client(group.repo_details)
                            repo = github.get_repo(group.repo_details.github_repo_id)
                            base_branch = repo.get_branch(group.repo_details.preferred_branch)
                            logger.debug(f"Base branch: {base_branch.name}")
                            
                            for task in imported_tasks:
                                if task.github_branch:
                                    try:
                                        repo.create_git_ref(
                                            ref=f"refs/heads/{task.github_branch}",
                                            sha=base_branch.commit.sha
                                        )
                                        logger.info(f"Created branch {task.github_branch} for task {task.task_id}")
                                    except Exception as e:
                                        logger.error(f"GitHub branch creation failed for task {task.task_id}: {str(e)}", exc_info=True)
                                        flash(f'Branch creation failed for task {task.name}', 'warning')
                        except Exception as e:
                            logger.error(f"GitHub connection failed: {str(e)}", exc_info=True)
                            flash('Task branches could not be created on GitHub', 'warning')
                    
                    db_session.commit()
                    logger.info(f"Successfully imported {len(imported_tasks)} tasks")
                    flash(f'Successfully imported {len(imported_tasks)} tasks', 'success')
                except Exception as e:
                    db_session.rollback()
                    logger.error(f"CSV import failed: {str(e)}", exc_info=True)
                    flash(f'Error processing CSV: {str(e)}', 'danger')
            return redirect(url_for('group.project_timeline'))
        
        # Manual Task Creation
        logger.info("Processing manual task creation")
        task_name = request.form.get('task_name')
        start_date_str = request.form.get('start_date')
        due_date_str = request.form.get('due_date')
        
        if task_name and start_date_str and due_date_str:
            try:
                logger.debug(f"Creating task: {task_name}")
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
                
                if start_date > due_date:
                    logger.warning("Invalid date range in task creation")
                    flash('Start date must be before due date', 'danger')
                    return redirect(url_for('group.project_timeline'))
                
                new_task = Task(
                    project_id=project.project_id,
                    name=task_name,
                    start_date=start_date,
                    due_date=due_date,
                    status='Not Started',
                    progress=0,
                    description=request.form.get('description', '')
                )
                db_session.add(new_task)
                db_session.flush()
                
                branch_name = f"task-{new_task.task_id}-{validate_branch_name(task_name)}"
                new_task.github_branch = branch_name
                logger.debug(f"Created task {new_task.task_id} with branch {branch_name}")
                
                # Handle dependencies
                if request.form.get('dependencies'):
                    for dep_id in request.form.get('dependencies').split(','):
                        dep_id = dep_id.strip()
                        if dep_id.isdigit():
                            db_session.add(TaskDependency(
                                task_id=new_task.task_id,
                                depends_on_id=int(dep_id)
                            ))
                            logger.debug(f"Added dependency: {new_task.task_id} -> {dep_id}")
                
                # Handle assignments
                assignees = request.form.getlist('assignees')
                for student_id in assignees:
                    if student_id:
                        assignment = TaskAssignment(
                            task_id=new_task.task_id,
                            student_id=int(student_id)
                        )
                        db_session.add(assignment)
                        logger.debug(f"Assigned task {new_task.task_id} to student {student_id}")
                
                # GitHub branch creation
                if group.repo_details and new_task.github_branch:
                    logger.info("Creating GitHub branch for new task")
                    try:
                        logger.debug("Authenticating with GitHub...")
                        github = GitHubIntegration.get_authenticated_client(group.repo_details)
                        repo = github.get_repo(group.repo_details.github_repo_id)
                        base_branch = repo.get_branch(group.repo_details.preferred_branch)
                        logger.debug(f"Creating branch from {base_branch.name}")
                        
                        repo.create_git_ref(
                            ref=f"refs/heads/{new_task.github_branch}",
                            sha=base_branch.commit.sha
                        )
                        logger.info(f"Created GitHub branch: {new_task.github_branch}")
                        flash(f'GitHub branch "{new_task.github_branch}" created', 'info')
                    except Exception as e:
                        logger.error(f"GitHub branch creation failed: {str(e)}", exc_info=True)
                        flash('Task created but GitHub branch creation failed', 'warning')
                
                db_session.commit()
                logger.info(f"Successfully created task {new_task.task_id}")
                flash('Task added successfully', 'success')
            except Exception as e:
                db_session.rollback()
                logger.error(f"Task creation failed: {str(e)}", exc_info=True)
                flash(f'Error creating task: {str(e)}', 'danger')
        
        return redirect(url_for('group.project_timeline'))
    
    # Calculate project progress
    try:
        logger.debug("Calculating project metrics")
        total_tasks = len(project.tasks)
        completed_tasks = sum(1 for t in project.tasks if t.status == 'Completed')
        project_progress = (completed_tasks / total_tasks * 100) if total_tasks else 0
        
        member_progress = {}
        github_stats = {
            'total_commits': 0,
            'open_prs': 0,
            'active_branches': 0
        }
        
        for task in project.tasks:
            for assignment in task.assignments:
                if assignment.student.name not in member_progress:
                    member_progress[assignment.student.name] = {'total': 0, 'count': 0}
                member_progress[assignment.student.name]['total'] += task.progress
                member_progress[assignment.student.name]['count'] += 1
            
            github_stats['total_commits'] += task.commit_count
            if task.pr_url:
                github_stats['open_prs'] += 1
            if task.github_branch:
                github_stats['active_branches'] += 1

        member_progress_data = []
        for member, data in member_progress.items():
            avg_progress = data['total'] / data['count'] if data['count'] else 0
            member_progress_data.append({
                'Member': member,
                'Progress': avg_progress,
                'TaskCount': data['count']
            })
        
        logger.debug("Rendering timeline template")
        return render_template('group/project_timeline.html',
                       group=group,
                       project=project,
                       tasks=project.tasks,
                       project_progress=round(project_progress, 1),
                       member_progress=member_progress_data,
                       github_stats=github_stats,
                       members=group.members,
                       datetime=datetime)
    
    except Exception as e:
        logger.error(f"Timeline generation failed: {str(e)}", exc_info=True)
        flash('Error generating timeline visualization', 'danger')
        return redirect(url_for('group.dashboard'))
    
def update_task(task_id):
    """Update task status with debug logging"""
    logger.info(f"Updating task {task_id}")
    
    if 'student_id' not in session:
        logger.warning("Unauthenticated task update attempt")
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    task = db_session.get(Task, task_id)
    if not task:
        logger.warning(f"Task {task_id} not found")
        flash('Task not found', 'danger')
        return redirect(url_for('group.project_timeline'))
    
    student_id = session['student_id']
    is_assigned = any(a.student_id == student_id for a in task.assignments)
    
    if not is_assigned:
        logger.warning(f"Student {student_id} attempted to update unassigned task {task_id}")
        flash('You are not assigned to this task', 'danger')
        return redirect(url_for('group.project_timeline'))
    
    if request.method == 'POST':
        try:
            new_status = request.form.get('status', task.status)
            new_progress = max(0, min(100, int(request.form.get('progress', task.progress))))
            
            if new_status == 'Completed' and new_progress < 100:
                new_progress = 100
            
            logger.debug(f"Updating task {task_id}: status={new_status}, progress={new_progress}")
            task.status = new_status
            task.progress = new_progress
            db_session.commit()
            logger.info(f"Successfully updated task {task_id}")
            flash('Task updated successfully', 'success')
        except Exception as e:
            db_session.rollback()
            logger.error(f"Task update failed: {str(e)}", exc_info=True)
            flash(f'Error updating task: {str(e)}', 'danger')
    
    return redirect(url_for('group.project_timeline'))