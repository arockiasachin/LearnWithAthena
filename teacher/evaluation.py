# [file name]: evaluation.py
# [file content begin]
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from database import db_session
from models import Groups, Project, Task, ProjectEvaluation, Teacher
from sqlalchemy.orm import joinedload
from datetime import datetime
import logging
from . import teacher_bp
logger = logging.getLogger(__name__)



RUBRIC = {
    'categories': [
        {
            'name': 'Code Quality',
            'max_score': 25,
            'weight': 0.3,
            'criteria': [
                'Readability and organization',
                'Proper error handling',
                'Efficiency of implementation',
                'Adherence to coding standards'
            ]
        },
        {
            'name': 'Functionality',
            'max_score': 30,
            'weight': 0.4,
            'criteria': [
                'All features implemented',
                'Correctness of output',
                'Error-free execution',
                'Meets project requirements'
            ]
        },
        {
            'name': 'Documentation',
            'max_score': 15,
            'weight': 0.1,
            'criteria': [
                'Code comments',
                'README quality',
                'API documentation',
                'Installation instructions'
            ]
        },
        {
            'name': 'Collaboration',
            'max_score': 15,
            'weight': 0.1,
            'criteria': [
                'Commit history quality',
                'Pull request management',
                'Issue tracking',
                'Team coordination'
            ]
        },
        {
            'name': 'Task Completion',
            'max_score': 15,
            'weight': 0.1,
            'criteria': [
                'Completed tasks percentage',
                'Meeting deadlines',
                'Bug resolution',
                'Testing coverage'
            ]
        }
    ],
    'total_max': 100
}

@teacher_bp.route('/evaluate_group/<int:group_id>', methods=['GET', 'POST'])
def evaluate_group(group_id):
    if 'teacher_id' not in session:
        flash('Authentication required', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    group = db_session.query(Groups).options(
        joinedload(Groups.projects),
        joinedload(Groups.repo_details),
        joinedload(Groups.members).joinedload(StudentGroup.student)
    ).get(group_id)
    
    if not group or not group.projects:
        flash('Group or project not found', 'danger')
        return redirect(url_for('teacher.group_management'))
    
    project = group.projects[0]
    teacher = db_session.get(Teacher, session['teacher_id'])
    
    if request.method == 'POST':
        try:
            scores = {}
            total = 0.0
            
            # Calculate scores based on rubric
            for category in RUBRIC['categories']:
                cat_score = float(request.form.get(f"score_{category['name']}"))
                if cat_score < 0 or cat_score > category['max_score']:
                    raise ValueError(f"Invalid score for {category['name']}")
                
                weighted = cat_score * category['weight']
                scores[category['name']] = {
                    'raw_score': cat_score,
                    'weighted_score': weighted,
                    'max_score': category['max_score']
                }
                total += weighted
            
            # Create evaluation record
            evaluation = ProjectEvaluation(
                group_id=group.group_id,
                evaluator_id=teacher.id,
                scores=scores,
                total_score=total,
                comments=request.form.get('comments', '')
            )
            
            db_session.add(evaluation)
            db_session.commit()
            flash('Evaluation submitted successfully', 'success')
            return redirect(url_for('teacher.group_management'))
            
        except Exception as e:
            db_session.rollback()
            logger.error(f"Evaluation failed: {str(e)}")
            flash(f'Evaluation failed: {str(e)}', 'danger')
    
    # Get GitHub data for reference
    github_data = {}
    if group.repo_details:
        try:
            access_token = decrypt_token(group.repo_details.repo_access_token)
            github_client = Github(access_token)
            repo = github_client.get_repo(group.repo_details.github_repo_id)
            
            github_data = {
                'branches': repo.get_branches().totalCount,
                'commits': repo.get_commits().totalCount,
                'pull_requests': repo.get_pulls(state='all').totalCount,
                'issues': repo.get_issues(state='all').totalCount,
                'readme': repo.get_readme().decoded_content.decode() if repo.get_readme() else None
            }
        except Exception as e:
            logger.warning(f"GitHub data fetch failed: {str(e)}")
            github_data['error'] = str(e)
    
    return render_template('teacher/evaluate_group.html',
                         group=group,
                         project=project,
                         rubric=RUBRIC,
                         github_data=github_data)
# [file content end]