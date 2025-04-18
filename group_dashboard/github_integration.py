# github_integration.py
from github import Github, GithubException
from models import Task, RepoDetails, TaskCommit
from database import db_session
from group_dashboard.github_utils import decrypt_token
from flask import current_app
import logging

logger = logging.getLogger(__name__)

class GitHubIntegration:
    @staticmethod
    def get_authenticated_client(repo_details: RepoDetails) -> Github:
        """Get authenticated GitHub client"""
        try:
            if not repo_details.repo_access_token:
                raise ValueError("No GitHub access token configured")
            access_token = decrypt_token(repo_details.repo_access_token)
            return Github(access_token)
        except Exception as e:
            logger.error(f"GitHub authentication failed: {str(e)}")
            raise

    @staticmethod
    def fetch_commit_diff(task: Task, sha: str) -> str:
        """Fetch full commit diff from GitHub"""
        try:
            repo_details = task.project.group.repo_details
            if not repo_details:
                raise ValueError("Repository not configured")

            github_client = GitHubIntegration.get_authenticated_client(repo_details)
            repo = github_client.get_repo(repo_details.github_repo_id)
            commit = repo.get_commit(sha)
            
            diff_contents = []
            for file in commit.files:
                diff_contents.append(
                    f"--- a/{file.filename}\n"
                    f"+++ b/{file.filename}\n"
                    f"{file.patch or ''}"
                )
            return "\n".join(diff_contents)
        except Exception as e:
            logger.error(f"Failed to fetch diff for commit {sha}: {str(e)}")
            raise

    @staticmethod
    def update_pr_status(task_id: int, pr_data: dict):
        """Update task status based on pull request state"""
        try:
            task = db_session.get(Task, task_id)
            if not task:
                return

            task.pr_url = pr_data['html_url']
            task.pr_state = pr_data['state']
            if pr_data['merged']:
                task.status = "Completed"
                task.progress = 100
            db_session.commit()
        except Exception as e:
            logger.error(f"Failed to update PR status: {str(e)}")
            db_session.rollback()
            raise