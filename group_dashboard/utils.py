from flask import session, flash
from models import Student, Groups, StudentGroup, Project, RepoDetails
from database import db_session
from datetime import datetime
import re
import random
import string

def validate_step1_data(form_data):
    """Validate step 1 form data"""
    if not form_data.get('name') or not form_data.get('identifier'):
        flash('Group name and identifier are required', 'danger')
        return False
    
    if len(form_data.get('identifier', '')) < 4:
        flash('Identifier must be at least 4 characters', 'danger')
        return False
    
    return True

def validate_step2_data(form_data):
    """Validate step 2 form data with improved checks"""
    members = []
    emails = set()
    
    for i in range(1, 6):
        name = form_data.get(f'name_{i}', '').strip()
        email = form_data.get(f'email_{i}', '').strip().lower()
        github = form_data.get(f'github_{i}', '').strip()
        
        if name and email:
            # Email validation using regex
            if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
                flash(f'Invalid email format for member {i}', 'danger')
                return None
                
            if email in emails:
                flash(f'Duplicate email found: {email}', 'danger')
                return None
                
            members.append({
                'name': name,
                'email': email,
                'github': github
            })
            emails.add(email)
    
    if len(members) < 1:
        flash('You need at least one additional member', 'danger')
        return None
        
    return members

def validate_step3_data(form_data):
    """Validate step 3 form data"""
    title = form_data.get('title', '').strip()
    if not title:
        flash('Project title is required', 'danger')
        return None
    
    if len(title) > 100:
        flash('Project title must be under 100 characters', 'danger')
        return None
    
    return {
        'title': title,
        'description': form_data.get('description', '').strip(),
        'tech_stack': form_data.getlist('tech_stack'),
        'milestones': form_data.get('milestones', '').strip()
    }

def validate_step4_data(form_data):
    """Validate step 4 form data"""
    repo_url = form_data.get('repo_url', '').strip()
    if not repo_url:
        flash('Repository URL is required', 'danger')
        return None
    
    if not repo_url.startswith('https://github.com/'):
        flash('Please provide a valid GitHub repository URL', 'danger')
        return None
    
    return {
        'url': repo_url,
        'token': form_data.get('access_token', '').strip(),
        'branch': form_data.get('branch', 'main').strip(),
        'privacy': form_data.get('privacy', 'public')
    }

def generate_group_identifier():
    """Generate GRP-XXXX where X is alphanumeric"""
    while True:
        identifier = f"GRP-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"
        # Ensure uniqueness
        if not db_session.query(Groups).filter_by(group_identifier=identifier).first():
            return identifier

def save_group_to_database():
    if 'group' not in session or 'name' not in session['group']:
        flash('Missing group information', 'danger')
        return False

    try:
        # Generate and validate identifier
        identifier = generate_group_identifier()
        if not identifier:
            flash('Failed to generate group ID', 'danger')
            return False

        # Create group with required fields
        group = Groups(
            name=session['group']['name'],
            group_identifier=identifier,
            created_at=datetime.utcnow()
        )
        db_session.add(group)
        db_session.flush()  # Get ID for relationships

        # Add creator as first member
        creator = StudentGroup(
            student_id=session['student_id'],
            group_id=group.group_id,
            role='creator',
            joined_at=datetime.utcnow()
        )
        db_session.add(creator)

        # Add other members from session
        for member_id in session.get('members', []):
            if member_id != session['student_id']:  # Skip creator
                db_session.add(StudentGroup(
                    student_id=member_id,
                    group_id=group.group_id,
                    role='member',
                    joined_at=datetime.utcnow()
                ))

        db_session.commit()
        return True

    except Exception as e:
        db_session.rollback()
        flash(f'Database error: {str(e)}', 'danger')
        return False
    
def clear_formation_session():
    """Clear all group formation related session data"""
    for key in ['group', 'members', 'project', 'repo']:
        session.pop(key, None)
        
