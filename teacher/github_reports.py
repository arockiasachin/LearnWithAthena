from flask import Blueprint, jsonify, send_file, flash, url_for, redirect, session, render_template,current_app
from database import db_session
from models import Groups, Project, Task, TaskCommit, RepoDetails, Student, TaskAssignment,StudentGroup
from sqlalchemy import func, and_,or_
from datetime import datetime, timedelta
from io import BytesIO
import csv
import os
import json
import re
from . import teacher_bp
import logging
from github import Github
from github.GithubException import GithubException
from group_dashboard.github_utils import decrypt_token
from sqlalchemy.orm import with_polymorphic, joinedload
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from collections import Counter
from langchain_deepseek import ChatDeepSeek
from langchain_community.document_loaders import GithubFileLoader
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

@teacher_bp.route('/github_report/<int:group_id>')
def generate_github_report(group_id):
    if 'teacher_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    group = db_session.query(Groups).options(
        joinedload(Groups.repo_details),
        joinedload(Groups.projects).joinedload(Project.tasks)
    ).get(group_id)
    
    if not group or not group.repo_details:
        return jsonify({'error': 'Group or repository not found'}), 404
    
    try:
        # Connect to GitHub API
        access_token = decrypt_token(group.repo_details.repo_access_token)
        github_client = Github(access_token)
        repo = github_client.get_repo(group.repo_details.github_repo_id)
        
        # Get basic repo info
        repo_info = {
            'name': repo.full_name,
            'url': repo.html_url,
            'branches': [b.name for b in repo.get_branches()],
            'open_issues': repo.open_issues_count,
            'forks': repo.forks_count,
            'stars': repo.stargazers_count
        }
        
        # Get recent activity
        commits = list(repo.get_commits(since=datetime.now() - timedelta(days=30)))
        recent_activity = {
            'commit_count': len(commits),
            'contributors': len({c.author.login for c in commits if c.author}),
            'last_commit': commits[0].last_modified if commits else None
        }
        
        # Get PRs
        prs = list(repo.get_pulls(state='all'))
        pr_stats = {
            'total': len(prs),
            'open': sum(1 for pr in prs if pr.state == 'open'),
            'merged': sum(1 for pr in prs if pr.merged),
            'closed': sum(1 for pr in prs if pr.state == 'closed' and not pr.merged)
        }
        
        return jsonify({
            'repo_info': repo_info,
            'recent_activity': recent_activity,
            'pr_stats': pr_stats
        })
        
    except GithubException as e:
        logger.error(f"GitHub API error: {str(e)}")
        return jsonify({'error': 'GitHub API error'}), 500
    except Exception as e:
        logger.error(f"Report generation failed: {str(e)}")
        return jsonify({'error': 'Report generation failed'}), 500

@teacher_bp.route('/export_contributions/<int:group_id>')
def export_contributions_csv(group_id):
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    group = db_session.get(Groups, group_id)
    if not group or not group.projects:
        flash('Group or project not found', 'danger')
        return redirect(url_for('teacher.group_progress'))
    
    project = group.projects[0]
    
    # Create CSV in memory
    output = BytesIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Student Name', 'Email', 'Tasks Assigned', 'Tasks Completed',
        'Avg Progress', 'Total Commits', 'Lines Added', 'Lines Deleted',
        'Last Activity'
    ])
    
    # Write data rows
    for member in group.members:
        student = member.student
        
        # Get assigned tasks via TaskAssignment join
        assigned_tasks = db_session.query(Task).join(TaskAssignment).filter(
            TaskAssignment.student_id == student.id,
            Task.project_id == project.project_id
        ).all()
        
        completed_tasks = sum(1 for t in assigned_tasks if t.status == 'Completed')
        avg_progress = (sum(t.progress for t in assigned_tasks) / len(assigned_tasks)) if assigned_tasks else 0
        
        commits = db_session.query(TaskCommit).join(Task).filter(
            Task.project_id == project.project_id,
            TaskCommit.author_email == student.email
        ).all()
        
        writer.writerow([
            student.name,
            student.email,
            len(assigned_tasks),
            completed_tasks,
            f"{avg_progress:.1f}%",
            len(commits),
            sum(c.additions for c in commits),
            sum(c.deletions for c in commits),
            max(c.timestamp for c in commits).strftime('%Y-%m-%d') if commits else 'None'
        ])
    
    output.seek(0)
    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"{group.group_identifier}_contributions.csv"
    )

def create_commit_analysis_chain(llm):
    return LLMChain(
        llm=llm,
        prompt=PromptTemplate(
            input_variables=["student_data", "commit_analysis"],
            template="""
            Generate a student code contribution report with these sections:
            
            1. **Activity Overview**: {commit_analysis['summary']}
            2. **Code Patterns**: 
               - File types: {commit_analysis['file_types']}
               - Avg changes/commit: {commit_analysis['avg_changes']}
               - Frequency: {commit_analysis['frequency']}
            3. **Quality Assessment**: 
               - {commit_analysis['quality_notes']}
            4. **Task Completion**: {student_data['task_stats']}
            5. **Recommendations**: Areas for improvement
            
            Use academic tone with technical specifics. Highlight notable contributions.
            """
        )
    )

@teacher_bp.route('/student_code_report/<int:group_id>/<int:student_id>')
def student_code_report(group_id, student_id):
    """Generate a detailed code contribution report for a specific student"""
    # Authentication and validation
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    student = db_session.get(Student, student_id)
    group = db_session.get(Groups, group_id)
    
    if not student or not group:
        flash('Student or group not found', 'danger')
        return redirect(url_for('teacher.group_detail', group_id=group_id))

    # Data collection
    try:
        # Get all tasks for the group's project
        project_id = group.projects[0].project_id if group.projects else None
        
        # Build email matching conditions
        email_conditions = [TaskCommit.author_email.ilike(student.email)]
        
        if student.github_username:
            # Handle both GitHub email formats
            github_patterns = [
                f"%{student.github_username}@users.noreply.github.com",  # Old format
                f"%+{student.github_username}@users.noreply.github.com"  # New format
            ]
            email_conditions.extend([TaskCommit.author_email.ilike(p) for p in github_patterns])

        # Get commits with proper matching
        commits = db_session.query(TaskCommit).join(Task).filter(
            Task.project_id == project_id,
            or_(*email_conditions)
        ).order_by(TaskCommit.timestamp.desc()).all()

        if not commits:
            flash('No commit data available for this student', 'warning')
            return redirect(url_for('teacher.group_detail', group_id=group_id))

        # Process commit data
        file_types = Counter()
        total_additions = 0
        total_deletions = 0
        commit_patterns = []

        for commit in commits:
            try:
                # File type analysis
                if commit.diff:
                    files = commit._extract_files_from_diff(commit.diff)
                    file_types.update([f.split('.')[-1].lower() for f in files if '.' in f])
                
                # Lines changed
                total_additions += commit.additions or 0
                total_deletions += commit.deletions or 0
                
                # Pattern detection
                if commit.additions > 100:
                    commit_patterns.append("Large additions")
                if 'fix' in commit.message.lower():
                    commit_patterns.append("Bug fixes")

            except Exception as e:
                logger.warning(f"Error processing commit {commit.id}: {str(e)}")
                continue

        # Get task statistics with proper project scope
        assigned_tasks = db_session.query(Task).join(TaskAssignment).filter(
            TaskAssignment.student_id == student.id,
            Task.project_id == project_id
        ).all()

        # Prepare report data
        report_data = {
            'student': {
                'name': student.name,
                'email': student.email,
                'tasks_assigned': len(assigned_tasks),
                'tasks_completed': sum(1 for t in assigned_tasks if t.status == 'Completed'),
                'completion_rate': round((sum(t.progress for t in assigned_tasks) / len(assigned_tasks)) 
                                       if assigned_tasks else 0)
            },
            'commits': {
                'total': len(commits),
                'additions': total_additions,
                'deletions': total_deletions,
                'file_types': dict(file_types.most_common(5)),
                'avg_changes': (total_additions + total_deletions) // max(1, len(commits)),
                'frequency': calculate_commit_frequency(commits),
                'patterns': list(set(commit_patterns))[:3]  # Top 3 unique patterns
            }
        }

        # Generate report using LLM
        llm = ChatDeepSeek(model="deepseek-chat", temperature=0)
        os.environ["DEEPSEEK_API_KEY"] = "API KEY"

        prompt_template = """\
Generate a professional student code contribution report with these exact sections:

# Code Contribution Report: {student_name}

## 1. Activity Summary
- Total commits: {total_commits}
- Lines changed: +{additions}/-{deletions}
- Primary file types: {file_types}

## 2. Work Patterns
- Average changes per commit: {avg_changes} lines
- Commit frequency: {commit_frequency}
- Notable patterns: {code_patterns}

## 3. Task Progress
- Tasks assigned: {tasks_assigned}
- Tasks completed: {tasks_completed} ({completion_rate}%)
- Completion status: {completion_status}

## 4. Recommendations
Provide 3-5 specific recommendations for improvement in bullet points:
- Focus on code quality practices
- Suggest collaboration improvements
- Include learning resources

Formatting Rules:
- Use exactly these section headers
- Maintain professional academic tone
- Be concise but thorough
- Highlight both strengths and areas for improvement
"""

        report = LLMChain(
            llm=llm,
            prompt=PromptTemplate(
                input_variables=[
                    'student_name', 'total_commits', 'additions', 
                    'deletions', 'file_types', 'avg_changes',
                    'commit_frequency', 'code_patterns', 'tasks_assigned',
                    'tasks_completed', 'completion_rate', 'completion_status'
                ],
                template=prompt_template
            )
        ).run({
            'student_name': report_data['student']['name'],
            'total_commits': report_data['commits']['total'],
            'additions': report_data['commits']['additions'],
            'deletions': report_data['commits']['deletions'],
            'file_types': ', '.join(f"{k} ({v})" for k,v in report_data['commits']['file_types'].items()),
            'avg_changes': report_data['commits']['avg_changes'],
            'commit_frequency': report_data['commits']['frequency'],
            'code_patterns': '; '.join(report_data['commits']['patterns']),
            'tasks_assigned': report_data['student']['tasks_assigned'],
            'tasks_completed': report_data['student']['tasks_completed'],
            'completion_rate': report_data['student']['completion_rate'],
            'completion_status': "On track" if report_data['student']['completion_rate'] > 75 
                               else "Needs improvement" if report_data['student']['completion_rate'] > 50 
                               else "Significantly behind"
        })

        return render_template('teacher/code_report.html',
                    report=report,
                    student=student,
                    analysis={
                        'total_commits': report_data['commits']['total'],
                        'additions': report_data['commits']['additions'],
                        'deletions': report_data['commits']['deletions'],
                        'file_types': report_data['commits']['file_types'],
                        'avg_changes': report_data['commits']['avg_changes'],
                        'frequency': report_data['commits']['frequency']
                    },
                    report_date=datetime.utcnow(),
                    reviewer_name=session.get('teacher_name', 'System'))

    except Exception as e:
        logger.error(f"Report generation failed: {str(e)}", exc_info=True)
        flash('Failed to generate report. Please try again.', 'danger')
        return redirect(url_for('teacher.group_detail', group_id=group_id))

def calculate_commit_frequency(commits):
    if not commits:
        return "No commits"
    dates = [c.timestamp.date() for c in commits]
    freq = max(Counter(dates).values())
    return f"{freq} commits/day at peak"

def detect_code_patterns(commits):
    patterns = []
    for commit in commits[-10:]:
        try:
            if commit.additions > 100:
                task_name = commit.task.name if commit.task else 'unknown task'
                patterns.append(f"Large additions ({commit.additions} lines) in {task_name}")
            if 'fix' in commit.message.lower():
                patterns.append("Bug fixes detected in: " + commit.message[:50])
        except Exception as e:
            logger.error(f"Pattern detection error: {str(e)}")
    return list(set(patterns))[:3]

@teacher_bp.route('/enhanced_github_report/<int:group_id>')
def enhanced_github_report(group_id):
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    group = db_session.query(Groups).options(
        joinedload(Groups.members).joinedload(StudentGroup.student),
        joinedload(Groups.projects)
    ).get(group_id)
    
    if not group or not group.projects:
        flash('Group or project not found', 'danger')
        return redirect(url_for('teacher.group_progress'))
    
    try:
        # Get all commits for the group's project
        commits = db_session.query(TaskCommit).join(Task).filter(
            Task.project_id == group.projects[0].project_id
        ).all()

        # Initialize metrics
        lines_added = 0
        lines_deleted = 0
        file_types = Counter()
        contributor_stats = {}

        # Prepare member email/username patterns
    
        # Prepare member email/username patterns
        member_patterns = []
        for member in group.members:
            student = member.student
            patterns = {
                'id': student.id,
                'name': student.name,
                'email': student.email.lower(),
                # Handle both old and new GitHub email formats
                'github_patterns': [
                    f"{student.github_username.lower()}@users.noreply.github.com",  # Old format
                    f"{student.github_username.lower()}",  # New format partial match
                    f"+{student.github_username.lower()}@"  # New format exact match
                ] if student.github_username else []
            }
            member_patterns.append(patterns)

        # Process commits
        for commit in commits:
            try:
                commit_email = commit.author_email.lower() if commit.author_email else ""
                matched_student = None
                
                for member in member_patterns:
                    # Check direct email match
                    if commit_email == member['email']:
                        matched_student = member
                        break
                    
                    # Check GitHub patterns if username exists
                    if member['github_patterns']:
                        for pattern in member['github_patterns']:
                            if pattern in commit_email:
                                matched_student = member
                                break
                        if matched_student:
                            break
                
                if matched_student:
                    # Update stats
                    if matched_student['id'] not in contributor_stats:
                        contributor_stats[matched_student['id']] = {
                            'name': matched_student['name'],
                            'commits': 0,
                            'lines_added': 0,
                            'lines_deleted': 0,
                            'email': matched_student['email'],
                            'commit_emails': set()  # Track all matched email formats
                        }
                    
                    contributor_stats[matched_student['id']]['commits'] += 1
                    contributor_stats[matched_student['id']]['lines_added'] += commit.additions if commit.additions else 0
                    contributor_stats[matched_student['id']]['lines_deleted'] += commit.deletions if commit.deletions else 0
                    contributor_stats[matched_student['id']]['commit_emails'].add(commit_email)
                    
                    # Debug logging
                    logger.debug(f"Matched commit {commit.id} from {commit_email} to student {matched_student['name']}")

            except Exception as e:
                logger.error(f"Error processing commit {commit.id}: {str(e)}")
                continue

        # ... [rest of the function remains the same] ...

        # Prepare top contributors list
        sorted_contributors = sorted(
            contributor_stats.values(),
            key=lambda x: x['commits'],
            reverse=True
        )
        top_contributors = [
            f"{c['name']} ({c['commits']})" 
            for c in sorted_contributors[:3]
        ]

        # Prepare analysis data
        analysis_data = {
            'total_commits': len(commits),
            'weekly_avg': len(commits) // 4 if len(commits) > 0 else 0,
            'top_contributors': top_contributors,
            'lines_added': lines_added,
            'lines_deleted': lines_deleted,
            'file_types': dict(file_types.most_common(5)),
            'contributor_details': sorted_contributors
        }

        # Generate report using LLM
        llm = ChatDeepSeek(model="deepseek-chat", temperature=0)
        os.environ["DEEPSEEK_API_KEY"] = "API KEY"
        
        template = """
        Generate a comprehensive GitHub activity report for group: {group_name}

        ### 1. Overview
        - Total commits: {total_commits}
        - Weekly average: {weekly_avg}
        - Lines changed: +{lines_added}/-{lines_deleted}

        ### 2. Top Contributors
        {top_contributors}

        ### 3. Code Analysis
        - Most modified file types: {file_types}
        - Code patterns detected: {code_patterns}

        ### 4. Recommendations
        - Strengths to highlight
        - Areas for improvement
        - Suggested learning resources

        Format as markdown with clear section headers.
        """
        
        prompt = PromptTemplate(
            input_variables=[
                'group_name', 'total_commits', 'weekly_avg', 
                'lines_added', 'lines_deleted', 'top_contributors',
                'file_types', 'code_patterns'
            ],
            template=template
        )
        
        report_chain = LLMChain(llm=llm, prompt=prompt)
        
        # Generate code patterns analysis
        code_patterns = detect_code_patterns_from_commits(commits)
        
        report = report_chain.run({
            'group_name': group.name,
            'total_commits': analysis_data['total_commits'],
            'weekly_avg': analysis_data['weekly_avg'],
            'lines_added': analysis_data['lines_added'],
            'lines_deleted': analysis_data['lines_deleted'],
            'top_contributors': "\n".join([f"- {c}" for c in analysis_data['top_contributors']]),
            'file_types': ", ".join([f"{k} ({v})" for k,v in analysis_data['file_types'].items()]),
            'code_patterns': "; ".join(code_patterns) if code_patterns else "No significant patterns detected"
        })

        return render_template('teacher/github_report.html',
                           group=group,
                           report=report,
                           metrics=analysis_data)

    except Exception as e:
        logger.error(f"Report generation failed: {str(e)}", exc_info=True)
        flash(f'Error generating report: {str(e)}', 'danger')
        return redirect(url_for('teacher.group_detail', group_id=group_id))

def detect_code_patterns_from_commits(commits):
    patterns = []
    for commit in commits[-20:]:  # Analyze last 20 commits
        try:
            # Detect large changes
            if commit.additions > 100:
                patterns.append(f"Large additions ({commit.additions} lines)")
            if commit.deletions > 50:
                patterns.append(f"Significant deletions ({commit.deletions} lines)")
            
            # Detect common patterns in commit messages
            msg = commit.message.lower()
            if 'fix' in msg:
                patterns.append("Bug fixes")
            if 'feat' in msg or 'feature' in msg:
                patterns.append("Feature implementations")
            if 'refactor' in msg:
                patterns.append("Code refactoring")
        except Exception as e:
            logger.warning(f"Error analyzing commit patterns: {str(e)}")
    
    # Return unique patterns
    return list(set(patterns))[:5]  # Limit to 5 most relevant patterns




from datetime import datetime
from flask import current_app

@teacher_bp.route('/task_code_report/<int:group_id>/<int:task_id>')
def task_code_report(group_id, task_id):
    """Generate a detailed code analysis report for a specific task"""
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    try:
        # Get task and group with relationships
        task = db_session.query(Task).options(
            joinedload(Task.project).joinedload(Project.group)
        ).get(task_id)
        
        if not task:
            flash('Task not found', 'danger')
            return redirect(url_for('teacher.group_progress'))

        group = task.project.group if task.project else None
        if not group or group.group_id != group_id:
            flash('Invalid group association', 'danger')
            return redirect(url_for('teacher.group_progress'))

        # Validate task has objectives/outcomes
        if not task.objectives and not task.outcomes:
            flash('This task has no defined objectives or outcomes', 'warning')
            return redirect(url_for('teacher.group_detail', group_id=group_id))

        # Check GitHub integration
        repo_details = group.repo_details
        if not repo_details or not task.github_branch:
            flash('GitHub integration not configured for this task', 'danger')
            return redirect(url_for('teacher.group_detail', group_id=group_id))

        # Extract repo info
        try:
            repo_parts = repo_details.github_repo_url.rstrip('/').split('/')
            repo_owner = repo_parts[-2]
            repo_name = repo_parts[-1].replace('.git', '')
        except Exception as e:
            current_app.logger.error(f"Error parsing repo URL: {str(e)}")
            flash('Invalid repository URL format', 'danger')
            return redirect(url_for('teacher.group_detail', group_id=group_id))

        # Load code files using LangChain
        try:
            loader = GithubFileLoader(
                repo=f"{repo_owner}/{repo_name}",
                access_token=repo_details.decrypted_token,
                branch=task.github_branch,
                file_filter=lambda file_path: file_path.endswith(
                    (".py", ".js", ".java", ".c", ".cpp", ".html", ".css", ".ts")
                )
            )
            documents = loader.load()
            
            if not documents:
                flash('No code files found in repository branch', 'warning')
                return redirect(url_for('teacher.group_detail', group_id=group_id))

            # Prepare code samples for analysis
            code_samples = []
            for doc in documents[:5]:  # Limit to 5 files
                ext = doc.metadata['path'].split('.')[-1]
                sample = {
                    'path': doc.metadata['path'],
                    'language': ext,
                    'content': doc.page_content[:1000]  # First 1000 chars
                }
                code_samples.append(sample)

        except Exception as e:
            current_app.logger.error(f"Error loading GitHub files: {str(e)}")
            flash('Error loading code from GitHub repository', 'danger')
            return redirect(url_for('teacher.group_detail', group_id=group_id))

        # Prepare enhanced analysis prompt
        prompt_template = ChatPromptTemplate.from_template(
            """**Task Code Analysis Report** - {task_name}

            **Project Context**: {project_desc}

            **Task Status**: {status} ({progress}% complete)
            **Branch**: {branch}
            **Last Updated**: {last_updated}

            **Task Objectives**:
            {objectives}

            **Expected Outcomes**:
            {outcomes}

            **Code Analysis**:

            1. **Objective Fulfillment**:
               - [ ] Map each objective to implemented code features
               - [ ] Identify gaps between requirements and implementation
               - [ ] Rate completeness (1-5 scale)

            2. **Outcome Validation**:
               - [ ] Verify measurable outcomes in code
               - [ ] Check test coverage for outcomes
               - [ ] Validate quantitative metrics

            3. **Code Quality Assessment**:
               - Structure and organization
               - Documentation quality
               - Error handling
               - Security considerations
               - Performance optimizations

            4. **Sample Code Review**:
               {code_samples}

            5. **Recommendations**:
               - Architectural improvements
               - Technical debt reduction
               - Learning resources
               - Security enhancements

            **Format**:
            - Use proper Markdown formatting
            - Include code snippets with language-specific highlighting
            - Provide concrete examples from the code
            - Summarize with an assessment matrix"""
        )

        # Generate report using LLM
        try:
            llm = ChatDeepSeek(model="deepseek-chat", temperature=0)
            os.environ["DEEPSEEK_API_KEY"] = "API KEY"
            chain = prompt_template | llm

            # Format code samples for prompt
            formatted_samples = "\n".join([
                f"### {sample['path']}\n```{sample['language']}\n{sample['content']}\n```"
                for sample in code_samples
            ])

            report = chain.invoke({
                "task_name": task.name,
                "project_desc": task.project.description or "No description available",
                "status": task.status,
                "progress": task.progress,
                "branch": task.github_branch,
                "last_updated": task.last_updated.strftime('%Y-%m-%d %H:%M'),
                "objectives": "\n".join([f"- {obj}" for obj in task.objectives]) if task.objectives else "No objectives defined",
                "outcomes": "\n".join([f"- {out}" for out in task.outcomes]) if task.outcomes else "No outcomes defined",
                "code_samples": formatted_samples
            })
            print(report.content)

            # Validate report content
            if not report.content.strip() or len(report.content) < 300:
                current_app.logger.error(f"Insufficient report content: {report.content[:100]}...")
                flash('Analysis failed to generate sufficient content', 'warning')
                return redirect(url_for('teacher.group_detail', group_id=group_id))

        except Exception as e:
            current_app.logger.error(f"Error generating AI report: {str(e)}", exc_info=True)
            flash('Error generating code analysis report', 'danger')
            return redirect(url_for('teacher.group_detail', group_id=group_id))

        return render_template('teacher/task_code_report.html',
                            report=report.content,
                            task=task,
                            group=group,
                            now=datetime.utcnow(),
                            code_samples=code_samples[:3])  # Pass first 3 samples to template

    except Exception as e:
        current_app.logger.error(f"Unexpected error in task_code_report: {str(e)}", exc_info=True)
        flash('An unexpected error occurred', 'danger')
        return redirect(url_for('teacher.group_progress'))
    
    
@teacher_bp.route('/task_evaluation_report/<int:group_id>')
def task_evaluation_report(group_id):
    """Generate comprehensive evaluation report across all tasks with code analysis"""
    if 'teacher_id' not in session:
        flash('Authentication required', 'danger')
        return redirect(url_for('auth.teacher_login'))

    try:
        # Load group with all required relationships
        group = db_session.query(Groups).options(
            joinedload(Groups.projects).joinedload(Project.tasks),
            joinedload(Groups.repo_details),
            joinedload(Groups.members).joinedload(StudentGroup.student)
        ).get(group_id)

        if not group or not group.projects:
            flash('Group or project not found', 'danger')
            return redirect(url_for('teacher.group_management'))

        if not group.repo_details:
            flash('GitHub repository not configured for this group', 'warning')
            return redirect(url_for('teacher.group_detail', group_id=group_id))

        # Initialize LLM
        llm = ChatDeepSeek(model="deepseek-chat", temperature=0)
        os.environ["DEEPSEEK_API_KEY"] = "API KEY"

        # Parse GitHub repository info
        try:
            repo_url = group.repo_details.github_repo_url.rstrip('/')
            repo_parts = repo_url.split('/')
            if len(repo_parts) < 2:
                raise ValueError("Invalid GitHub URL format")
            
            repo_owner = repo_parts[-2]
            repo_name = repo_parts[-1].replace('.git', '')
            repo_path = f"{repo_owner}/{repo_name}"
            github_base_url = f"https://github.com/{repo_path}"
        except Exception as e:
            logger.error(f"Error parsing GitHub URL: {str(e)}")
            flash('Invalid GitHub repository URL format', 'danger')
            return redirect(url_for('teacher.group_detail', group_id=group_id))

        # Define evaluation prompt with proper escaping
        evaluation_prompt = ChatPromptTemplate.from_template(
            """Analyze the code quality and task completion for this programming task.
            Return your evaluation in this exact JSON format:
            {{
                "code_quality": score (1-5),
                "functionality": score (1-5),
                "documentation": score (1-5),
                "analysis": "detailed comments",
                "recommendations": ["list", "of", "improvements"]
            }}
            
            Grading Rubric:
            1. Code Quality (1-5):
               - 1: Poor structure, unreadable, no error handling
               - 3: Adequate structure, somewhat readable, basic error handling  
               - 5: Excellent structure, highly readable, robust error handling
               
            2. Functionality (1-5):
               - 1: Doesn't work, major bugs
               - 3: Partially works, some bugs
               - 5: Fully works, meets all requirements
               
            3. Documentation (1-5):
               - 1: No comments or docs
               - 3: Some comments, basic docs
               - 5: Comprehensive comments, excellent docs
            
            Task: {task_name}
            Objectives: {objectives}
            Status: {status}
            Branch: {branch}
            
            Code Analysis:
            {code_samples}"""
        )

        chain = evaluation_prompt | llm
        task_evaluations = []  # Changed from evaluations to task_evaluations
        score_weights = {
            'code_quality': 0.4,
            'functionality': 0.4,
            'documentation': 0.2
        }

        # Process each task
        for task in group.projects[0].tasks:
            task_eval = {
                'task': task,
                'github_url': f"{github_base_url}/tree/{task.github_branch}" if task.github_branch else None,
                'code_quality': 0,
                'functionality': 0,
                'documentation': 0,
                'weighted_score': 0,
                'analysis': "Evaluation failed - no GitHub branch",
                'recommendations': ["No recommendations available"]
            }

            if not task.github_branch:
                task_evaluations.append(task_eval)
                continue

            try:
                # Load code files from GitHub
                loader = GithubFileLoader(
                    repo=repo_path,
                    access_token=group.repo_details.decrypted_token,
                    branch=task.github_branch,
                    file_filter=lambda fp: fp.endswith(('.py', '.js', '.java', '.html', '.css', '.md'))
                )
                documents = loader.load()

                # Get representative code samples (first 3 files)
                code_samples = "\n\n".join(
                    f"File: {doc.metadata['path']}\n```{doc.metadata['path'].split('.')[-1]}\n{doc.page_content[:1000]}\n```"
                    for doc in documents[:3]
                ) if documents else "No code files found"

                # Get evaluation from LLM
                response = chain.invoke({
                    "task_name": task.name,
                    "objectives": "\n- ".join(task.objectives) if task.objectives else "No objectives defined",
                    "status": task.status,
                    "branch": task.github_branch,
                    "code_samples": code_samples
                })

                # Parse evaluation
                evaluation = parse_evaluation_response(response.content)
                evaluation.update({
                    'task': task,
                    'github_url': f"{github_base_url}/tree/{task.github_branch}",
                    'weighted_score': (
                        evaluation.get('code_quality', 0) * score_weights['code_quality'] +
                        evaluation.get('functionality', 0) * score_weights['functionality'] +
                        evaluation.get('documentation', 0) * score_weights['documentation']
                    )
                })

                task_evaluations.append(evaluation)

            except Exception as e:
                logger.error(f"Failed to evaluate task {task.task_id}: {str(e)}")
                task_eval.update({
                    'analysis': f"Evaluation failed: {str(e)}",
                    'recommendations': ["See error logs for details"]
                })
                task_evaluations.append(task_eval)

        # Calculate overall scores
        valid_evals = [e for e in task_evaluations if e.get('weighted_score', 0) > 0]
        avg_scores = {
            'code_quality': sum(e.get('code_quality', 0) for e in valid_evals) / len(valid_evals) if valid_evals else 0,
            'functionality': sum(e.get('functionality', 0) for e in valid_evals) / len(valid_evals) if valid_evals else 0,
            'documentation': sum(e.get('documentation', 0) for e in valid_evals) / len(valid_evals) if valid_evals else 0,
            'weighted': sum(e.get('weighted_score', 0) for e in valid_evals) / len(valid_evals) if valid_evals else 0
        }

        return render_template('teacher/task_evaluation_report.html',
                            group=group,
                            task_evaluations=task_evaluations,  # Changed to match template
                            average_scores=avg_scores,
                            now=datetime.utcnow(),
                            rubrics=score_weights,
                            github_base_url=github_base_url)

    except Exception as e:
        logger.error(f"Evaluation report generation failed: {str(e)}", exc_info=True)
        flash(f'Failed to generate evaluation report: {str(e)}', 'danger')
        return redirect(url_for('teacher.group_detail', group_id=group_id))

def parse_evaluation_response(response: str) -> dict:
    """Parse the LLM evaluation response into structured data"""
    try:
        # Try to extract JSON
        json_str = re.search(r'\{.*\}', response, re.DOTALL)
        if json_str:
            data = json.loads(json_str.group())
        else:
            raise ValueError("No JSON found in response")
            
        # Validate scores
        for key in ['code_quality', 'functionality', 'documentation']:
            if key not in data or not (1 <= data[key] <= 5):
                data[key] = 3  # Default if invalid
                
        # Ensure all required fields exist
        data.setdefault('analysis', 'No analysis provided')
        data.setdefault('recommendations', [])
        
        return data
        
    except Exception as e:
        logger.warning(f"Failed to parse evaluation response: {str(e)}")
        return {
            'code_quality': 3,
            'functionality': 3,
            'documentation': 3,
            'analysis': f"Could not parse evaluation: {str(e)}",
            'recommendations': ["Check evaluation format"]
        }