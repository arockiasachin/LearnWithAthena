from github import Github, GithubException
from models import Task, RepoDetails, Groups, TaskCommit, Student
from database import db_session
from datetime import datetime, timedelta
from flask import current_app
import logging
from sqlalchemy import func, case, and_, or_

logger = logging.getLogger(__name__)

def poll_github_activity(app):
    """Main function to poll GitHub for all groups' activity with better logging."""
    with app.app_context():
        try:
            logger.info("=== Starting GitHub Polling Cycle ===")
            
            groups = db_session.query(Groups).join(RepoDetails).all()
            logger.info(f"Found {len(groups)} groups with GitHub repos to check")
            
            for group in groups:
                if not group.repo_details:
                    logger.debug(f"Skipping group {group.group_id} - no repo details")
                    continue
                
                logger.info(f"\nProcessing group: {group.name} (ID: {group.group_id})")
                logger.info(f"Repo URL: {group.repo_details.github_repo_url}")
                
                try:
                    github = Github(group.repo_details.decrypted_token)
                    repo = github.get_repo(group.repo_details.github_repo_id)
                    logger.info(f"Repository: {repo.full_name} (ID: {repo.id})")
                    
                    # Log rate limits
                    rate_limit = github.get_rate_limit()
                    logger.debug(f"GitHub API rate limits - Remaining: {rate_limit.core.remaining}")
                    
                    for project in group.projects:
                        logger.info(f"\nChecking project: {project.name} (ID: {project.project_id})")
                        logger.info(f"Total tasks: {len(project.tasks)}")
                        
                        for task in project.tasks:
                            logger.info(f"\nProcessing task: {task.name} (ID: {task.task_id})")
                            if task.github_branch:
                                logger.info(f"GitHub branch: {task.github_branch}")
                            else:
                                logger.warning("No GitHub branch associated with this task")
                            
                            _update_task_commits(task, repo)
                            _update_pr_status(task, repo)
                            
                except GithubException as ge:
                    logger.error(f"GitHub API error for group {group.group_id}: {str(ge)}")
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error processing group {group.group_id}: {str(e)}")
                    continue
            
            logger.info("\n=== GitHub Polling Completed Successfully ===")
            
        except Exception as e:
            logger.error(f"\n!!! Critical error in polling job: {str(e)}", exc_info=True)
            raise

def _update_task_commits(task: Task, repo):
    """Check for new commits in a task's branch with enhanced error handling."""
    if not task.github_branch:
        logger.debug(f"No GitHub branch for task {task.task_id}")
        return

    try:
        # Get branch with error handling
        try:
            branch = repo.get_branch(task.github_branch)
            logger.debug(f"Branch info - SHA: {branch.commit.sha}")
        except GithubException as e:
            if e.status == 404:
                logger.warning(f"Branch '{task.github_branch}' not found in repository")
                return
            raise

        # Get commits since last poll
        since_date = task.last_polled_at or datetime.utcnow() - timedelta(days=7)
        logger.info(f"Looking for commits since: {since_date.isoformat()}")
        
        commits = list(repo.get_commits(
            sha=task.github_branch,
            since=since_date
        ))
        
        logger.info(f"Found {len(commits)} new commits in branch '{task.github_branch}'")

        for commit in reversed(commits):
            if db_session.query(TaskCommit).filter_by(sha=commit.sha).first():
                logger.debug("Commit already exists in database, skipping")
                continue

            try:
                # Get the full commit details
                full_commit = repo.get_commit(commit.sha)
                
                # Get the diff separately since it's not always available
                try:
                    diff = full_commit.files[0].patch if full_commit.files else ""
                except Exception as diff_error:
                    logger.debug(f"Could not get diff for commit {commit.sha}: {str(diff_error)}")
                    diff = ""
                
                new_commit = TaskCommit(
                    task_id=task.task_id,
                    sha=commit.sha,
                    message=commit.commit.message[:500],
                    timestamp=commit.commit.author.date,
                    author_email=commit.commit.author.email,
                    additions=full_commit.stats.additions,
                    deletions=full_commit.stats.deletions,
                    diff=diff,
                )
                db_session.add(new_commit)
                _update_student_stats(task, commit)
                
                # Update task's last commit info
                task.last_commit_time = commit.commit.author.date
                task.last_commit_message = commit.commit.message[:200]
                task.commit_count += 1
                
                logger.info(f"Added commit: {commit.sha[:7]} - {commit.commit.message[:50]}...")
                
            except Exception as e:
                logger.error(f"Error processing commit {commit.sha}: {str(e)}", exc_info=True)
                continue

        task.last_polled_at = datetime.utcnow()
        db_session.commit()
        logger.info(f"Successfully updated {len(commits)} commits for task {task.task_id}")

    except Exception as e:
        db_session.rollback()
        logger.error(f"Failed to update commits for task {task.task_id}: {str(e)}", exc_info=True)

def _update_pr_status(task: Task, repo):
    """Check PR status for a task with enhanced logging."""
    if not task.pr_url:
        logger.debug(f"No PR URL for task {task.task_id}")
        return

    try:
        logger.info(f"\nChecking PR status for task {task.task_id}")
        logger.info(f"PR URL: {task.pr_url}")
        
        pr_number = int(task.pr_url.split("/")[-1])
        pr = repo.get_pull(pr_number)
        
        logger.info(f"PR State: {pr.state}, Merged: {pr.merged}")
        logger.debug(f"PR Details - Title: {pr.title}, Created: {pr.created_at}, Updated: {pr.updated_at}")
        
        if pr.merged and task.status != "Completed":
            logger.info(f"Marking task {task.task_id} as completed (PR merged)")
            task.status = "Completed"
            task.progress = 100
            db_session.commit()
            
    except Exception as e:
        logger.error(f"Failed to check PR status for task {task.task_id}: {str(e)}")

def _update_student_stats(task: Task, commit):
    """Update student contribution statistics with GitHub login"""
    try:
        commit_email = commit.commit.author.email.lower()
        github_login = commit.author.login.lower() if commit.author else None
        
        # Build query conditions
        conditions = [
            Student.email == commit_email,
        ]
        
        # Add GitHub username conditions if available
        if github_login:
            conditions.append(Student.github_username == github_login)
        
        # Add GitHub email pattern conditions
        if '@users.noreply.github.com' in commit_email:
            username_part = commit_email.split('@')[0]
            # Handle both new (ID+username) and old (username) formats
            possible_usernames = [username_part.split('+')[-1]] if '+' in username_part else [username_part]
            
            for username in possible_usernames:
                conditions.append(
                    and_(
                        Student.github_username == username,
                        func.lower(commit_email).endswith('@users.noreply.github.com')
                    )
                )

        # Find matching student
        student = db_session.query(Student).filter(or_(*conditions)).first()

        if not student:
            logger.warning(f"No student found for commit {commit.sha}")
            return

        # Initialize stats if not exists
        if task.student_stats is None:
            task.student_stats = {}
            
        # Update stats
        student_email = student.email.lower()
        current_stats = task.student_stats.get(student_email, {"commits": 0, "last_commit": ""})
        current_stats["commits"] += 1
        current_stats["last_commit"] = commit.commit.author.date.isoformat()
        task.student_stats[student_email] = current_stats
        
        logger.debug(f"Updated stats for {student.name}: {current_stats}")

    except Exception as e:
        logger.error(f"Error updating stats for commit {commit.sha}: {str(e)}", exc_info=True)
        raise
    