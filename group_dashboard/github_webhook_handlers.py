# github_webhook_handlers.py
from group_dashboard.github_integration import GitHubIntegration
from models import Task, Student, TaskCommit
from database import db_session
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

class WebhookHandlers:
    @staticmethod
    def handle_push_event(payload: dict):
        branch = payload.get('ref', '').split('/')[-1]
        task_match = re.match(r'task-(\d+)-', branch)
        
        if not task_match:
            return

        task_id = int(task_match.group(1))
        task = db_session.get(Task, task_id)
        if not task:
            return

        for commit in payload.get('commits', []):
            WebhookHandlers._process_commit(task, commit)

    @staticmethod
    def _process_commit(task: Task, commit_data: dict):
        """Process individual commit and update tracking"""
        try:
            diff = GitHubIntegration.fetch_commit_diff(task, commit_data['id'])
            
            task_commit = TaskCommit(
                task_id=task.task_id,
                sha=commit_data['id'],
                message=commit_data['message'],
                timestamp=datetime.fromisoformat(commit_data['timestamp']),
                author_email=commit_data['author']['email'],
                additions=len(commit_data.get('added', [])),
                deletions=len(commit_data.get('removed', [])),
                diff=diff
            )
            db_session.add(task_commit)
            WebhookHandlers._update_student_stats(task, commit_data)
            db_session.commit()
        except Exception as e:
            logger.error(f"Error processing commit: {str(e)}")
            db_session.rollback()
            raise

    @staticmethod
    def _update_student_stats(task: Task, commit_data: dict):
        student = db_session.query(Student).filter(
            Student.email == commit_data['author']['email']
        ).first()
        
        if student:
            task.student_stats.setdefault(
                student.email,
                {'commits': 0, 'last_commit': ''}
            )
            task.student_stats[student.email]['commits'] += 1
            task.student_stats[student.email]['last_commit'] = commit_data['timestamp']

    @staticmethod
    def handle_pr_event(payload: dict):
        """Handle pull request events with better validation"""
        try:
            if not payload.get('pull_request', {}).get('merged'):
                return
                
            pr_data = payload['pull_request']
            branch = pr_data['head']['ref']
            
            task_match = re.match(r'(?:revert-\d+-)?task-(\d+)', branch)
            if task_match:
                task_id = int(task_match.group(1))
                GitHubIntegration.update_pr_status(task_id, pr_data)
                    
        except Exception as e:
            logger.error(f"PR event handling failed: {str(e)}", exc_info=True)
            db_session.rollback()

    @staticmethod
    def handle_issue_event(payload: dict):
        """Handle GitHub issue events (for future use)"""
        pass

    @staticmethod
    def handle_branch_tag_event(payload: dict):
        """Handle branch/tag creation events (for future use)"""
        pass