from github import Github, GithubException
from models import RepoDetails
from database import db_session
import logging
import re
from itsdangerous import URLSafeSerializer
from flask import current_app

logger = logging.getLogger(__name__)

def encrypt_token(token):
    """Encrypt GitHub access token before storage"""
    s = URLSafeSerializer(current_app.config['SECRET_KEY'])
    return s.dumps(token)

def decrypt_token(encrypted_token):
    """Decrypt GitHub access token"""
    s = URLSafeSerializer(current_app.config['SECRET_KEY'])
    return s.loads(encrypted_token)

def create_github_repo(group, project_name, access_token, is_private=True):
    """Create a GitHub repo using the project name"""
    try:
        # Validate inputs
        if not all([group, project_name, access_token]):
            raise ValueError("Missing required parameters")
            
        if not isinstance(is_private, bool):
            raise TypeError("is_private must be boolean")

        g = Github(access_token)
        user = g.get_user()
        
        # Clean and format repo name
        repo_name = f"{group.group_identifier}-{slugify(project_name)}"
        if len(repo_name) > 100:
            repo_name = repo_name[:100]
            logger.warning(f"Truncated repository name to {repo_name}")
        
        # Create repository with more configuration
        try:
            repo = user.create_repo(
                name=repo_name,
                description=f"{project_name} - {group.name}'s project",
                private=is_private,
                auto_init=True,
                gitignore_template="Python",  # Default to Python
                license_template="mit"  # Default to MIT license
            )
        except GithubException as e:
            if "name already exists" in str(e).lower():
                # Handle naming conflicts
                repo_name = f"{repo_name}-{group.group_id}"
                repo = user.create_repo(
                    name=repo_name,
                    description=f"{project_name} - {group.name}'s project",
                    private=is_private,
                    auto_init=True
                )
            else:
                raise

        # Encrypt the access token before storage
        encrypted_token = encrypt_token(access_token)
        
        # Save repo details
        repo_details = RepoDetails(
            group_id=group.group_id,
            github_repo_url=repo.html_url,
            github_repo_id=repo.id,
            repo_access_token=encrypted_token,
            preferred_branch='main',
            repo_privacy='private' if is_private else 'public'
        )
        
        db_session.add(repo_details)
        db_session.commit()
        
        logger.info(f"Created GitHub repository: {repo.html_url}")
        return repo
        
    except Exception as e:
        logger.error(f"GitHub repo creation failed: {str(e)}", exc_info=True)
        db_session.rollback()
        return None

def slugify(text):
    """Convert text to a safe repo name with more comprehensive cleaning"""
    if not text:
        return ""
        
    text = str(text).lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)  # Remove special chars
    text = re.sub(r'[\s_-]+', '-', text)  # Replace spaces/underscores with dashes
    text = re.sub(r'^-+|-+$', '', text)   # Remove leading/trailing dashes
    return text or "project"  # Default if empty after cleaning