from flask import request, session, redirect, url_for, flash, render_template
from models import Student, Groups, Project, StudentGroup, RepoDetails
from database import db_session
from group_dashboard.github_utils import create_github_repo, encrypt_token
import logging
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from github import GithubException
import re

logger = logging.getLogger(__name__)

def validate_github_token(token):
    """Basic validation of GitHub token format"""
    return bool(token and re.match(r'^ghp_[a-zA-Z0-9]{36}$', token))

def formation_step4():
    """Handle GitHub repository creation with enhanced security"""
    try:
        logger.info("STEP4: Starting group formation step 4")
        
        # Authentication and session validation
        if 'student_id' not in session:
            logger.warning("STEP4: Unauthenticated access attempt")
            flash('Please log in first', 'danger')
            return redirect(url_for('auth.student_login'))

        if 'group_id' not in session:
            logger.error("STEP4: Missing group_id in session")
            flash('Group formation session expired', 'danger')
            return redirect(url_for('group.formation.formation_step1'))

        group_id = session['group_id']
        group = db_session.get(Groups, group_id)
        
        if not group:
            logger.error(f"STEP4: Group {group_id} not found")
            flash('Group not found', 'danger')
            return redirect(url_for('group.formation.formation_step1'))

        # Verify user is in the group
        student_in_group = db_session.query(StudentGroup).filter_by(
            student_id=session['student_id'],
            group_id=group_id
        ).first()
        
        if not student_in_group:
            logger.warning(f"STEP4: Student {session['student_id']} not in group {group_id}")
            flash('You are not a member of this group', 'danger')
            return redirect(url_for('group.dashboard'))

        # Handle POST request
        if request.method == 'POST':
            logger.info("STEP4: Processing repository creation request")
            token = request.form.get('access_token', '').strip()
            privacy = request.form.get('privacy', 'public')
            
            # Token validation
            if not validate_github_token(token):
                logger.warning("STEP4: Invalid GitHub token format")
                flash('Invalid GitHub token format', 'danger')
                return render_template('group/step4.html', step=4)

            # Verify project exists
            if not group.projects:
                logger.error("STEP4: No project exists for group")
                flash('Please create a project first', 'danger')
                return redirect(url_for('group.formation.formation_step3'))

            try:
                # Create repository with error handling
                logger.info(f"STEP4: Attempting to create repo for group {group_id}")
                repo = create_github_repo(
                    group=group,
                    project_name=group.projects[0].name,
                    access_token=token,
                    is_private=(privacy == 'private')
                )

                if not repo:
                    logger.error("STEP4: Repository creation returned None")
                    flash('GitHub repository creation failed', 'danger')
                    return redirect(url_for('group.formation.formation_step4'))

                logger.info(f"STEP4: Created repo {repo.html_url} (ID: {repo.id})")

                # Encrypt token before storage
                encrypted_token = encrypt_token(token)
                
                # Check for existing repository
                existing_repo = db_session.query(RepoDetails).filter_by(
                    group_id=group.group_id
                ).first()

                if existing_repo:
                    logger.info("STEP4: Updating existing repository details")
                    existing_repo.github_repo_id = repo.id
                    existing_repo.github_repo_url = repo.html_url
                    existing_repo.repo_access_token = encrypted_token
                    existing_repo.preferred_branch = 'main'
                    existing_repo.repo_privacy = privacy
                else:
                    logger.info("STEP4: Creating new repository record")
                    repo_details = RepoDetails(
                        group_id=group.group_id,
                        github_repo_id=repo.id,
                        github_repo_url=repo.html_url,
                        repo_access_token=encrypted_token,
                        preferred_branch='main',
                        repo_privacy=privacy
                    )
                    db_session.add(repo_details)

                db_session.commit()
                logger.info("STEP4: Repository details saved successfully")
                
                # Clean up session
                session.pop('group_id', None)
                
                flash('GitHub repository configured successfully!', 'success')
                return redirect(url_for('group.dashboard'))

            except GithubException as ge:
                db_session.rollback()
                logger.error(f"STEP4: GitHub API error: {str(ge)}", exc_info=True)
                error_msg = f"GitHub error: {ge.data.get('message', 'Unknown error')}"
                flash(error_msg, 'danger')
                return redirect(url_for('group.formation.formation_step4'))

            except IntegrityError as ie:
                db_session.rollback()
                logger.error(f"STEP4: Database integrity error: {str(ie)}", exc_info=True)
                flash('Database error occurred', 'danger')
                return redirect(url_for('group.formation.formation_step4'))

            except Exception as e:
                db_session.rollback()
                logger.error(f"STEP4: Unexpected error: {str(e)}", exc_info=True)
                flash('Repository setup failed', 'danger')
                return redirect(url_for('group.formation.formation_step4'))

        # GET request handling
        logger.info("STEP4: Rendering repository setup form")
        return render_template('group/step4.html', 
                           step=4,
                           has_project=bool(group.projects))

    except Exception as e:
        db_session.rollback()
        logger.critical(f"STEP4: System error: {str(e)}", exc_info=True)
        flash('An unexpected error occurred', 'danger')
        return redirect(url_for('group.formation.formation_step4'))