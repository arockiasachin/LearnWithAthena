from typing import List, Optional, Dict, Any, Union
from sqlalchemy import (
    DateTime, Enum, ForeignKey, Integer, String, Text, 
    select, func, Float, CheckConstraint, Date, JSON, 
    Boolean, Index, Column, UniqueConstraint  
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, 
    relationship, foreign, remote, Session, 
    aliased, validates, with_polymorphic
)
from testcase_functions import testcase_chain, parse_testcases
from datetime import datetime, timezone, date
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.sql.expression import case, cast
from sqlalchemy.dialects.postgresql import ARRAY, UUID
import os
import re
import pandas as pd
from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash
from github import Github

class Base(DeclarativeBase):
    pass

class Student(Base):
    __tablename__ = 'students'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    register_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    github_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Relationships
    fslsm_result: Mapped['FSLSMResult'] = relationship('FSLSMResult', back_populates='student', uselist=False)
    subject_associations: Mapped[List['StudentSubject']] = relationship('StudentSubject', back_populates='student')
    groups: Mapped[List['StudentGroup']] = relationship('StudentGroup', back_populates='student')
    assignment_submissions: Mapped[List['AssignmentSubmission']] = relationship(
        'AssignmentSubmission', 
        back_populates='student'
    )
    quiz_attempts: Mapped[List['QuizAttempt']] = relationship(
        'QuizAttempt', 
        back_populates='student',
        cascade='all, delete-orphan'
    )
    
    @property
    def profile_complete(self):
        """Check if required profile fields are filled"""
        return all([
            self.register_number,
            self.github_username,
            bool(self.subject_associations)  # Changed from self.subjects to self.subject_associations
        ])
    @property
    def github_avatar(self):
        if self.github_username:
            return f"https://github.com/{self.github_username}.png"
        return None
    
    def verify_commit_author(self, commit_email: str) -> bool:
        """Check if commit email matches student's registered email"""
        return self.email.lower() == commit_email.lower()

class StudentSubject(Base):
    __tablename__ = 'student_subjects'
    
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'), primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'), primary_key=True)
    enrolled_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    priority: Mapped[int] = mapped_column(Integer, default=0) 
    # Relationships
    student: Mapped['Student'] = relationship('Student', back_populates='subject_associations')
    subject: Mapped['Subject'] = relationship('Subject', back_populates='student_associations')

class Groups(Base):
    __tablename__ = 'groups'

    group_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_identifier: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    generation_method: Mapped[Optional[str]] = mapped_column(
        String(50), 
        nullable=True, 
        comment="How the group was formed (e.g., fslsm_heterogeneous_dynamic)"
    )
    # Relationships
    members: Mapped[List['StudentGroup']] = relationship('StudentGroup', back_populates='group')
    projects: Mapped[List['Project']] = relationship('Project', back_populates='group')
    repo_details: Mapped['RepoDetails'] = relationship(
    'RepoDetails', 
    back_populates='group', 
    uselist=False,
    cascade='all, delete-orphan'  # Add cascade deletion
    )
    evaluations: Mapped[List['ProjectEvaluation']] = relationship('ProjectEvaluation', back_populates='group')
    
class StudentGroup(Base):
    __tablename__ = 'student_groups'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'))
    group_id: Mapped[int] = mapped_column(ForeignKey('groups.group_id'))
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    role: Mapped[str] = mapped_column(String(50), default='member')
    
    # Relationships
    student: Mapped['Student'] = relationship('Student', back_populates='groups')
    group: Mapped['Groups'] = relationship('Groups', back_populates='members')

class Project(Base):
    __tablename__ = 'projects'
    
    project_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('groups.group_id'))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    tech_stack: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    milestones: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), default='planning')
    
    # Relationships
    group: Mapped['Groups'] = relationship('Groups', back_populates='projects')
    tasks: Mapped[List['Task']] = relationship('Task', back_populates='project')
    
    def get_contribution_report(self):
        """Aggregate contribution data for LangChain reports"""
        return {
            'project_id': self.project_id,
            'total_commits': sum(len(t.commits) for t in self.tasks),
            'member_contributions': {
                s.student.email: {
                    'commits': sum(1 for c in t.commits if c.author_email == s.student.email)
                    for t in self.tasks
                }
                for s in self.group.members
            }
        }
class TaskAssignment(Base):
    __tablename__ = 'task_assignments'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.task_id'))
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'))
    role: Mapped[str] = mapped_column(String(50), default='member')
    assigned_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    # Relationships
    task: Mapped['Task'] = relationship('Task', back_populates='assignments')
    student: Mapped['Student'] = relationship('Student')




class TaskCommit(Base):
    __tablename__ = 'task_commits'
    __table_args__ = (
        Index('ix_taskcommit_author_email', 'author_email'),
        Index('ix_taskcommit_task_id', 'task_id'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.task_id'))
    sha: Mapped[str] = mapped_column(String(64), unique=True)  # GitHub commit SHA
    message: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    author_email: Mapped[str] = mapped_column(String(150))
    
    # Code diffs (unified diff format)
    additions: Mapped[int] = mapped_column(Integer)  # Lines added
    deletions: Mapped[int] = mapped_column(Integer)  # Lines removed
    diff: Mapped[str] = mapped_column(Text)          # Git patch format
    
    # Relationships
    task: Mapped['Task'] = relationship('Task', back_populates='commits')
    
class Task(Base):
    __tablename__ = 'tasks'
    __table_args__ = (
        Index('ix_task_github_branch', 'github_branch'),
        Index('ix_task_project_status', 'project_id', 'status'),
        CheckConstraint('progress >= 0 AND progress <= 100', name='check_progress_range'),
        CheckConstraint(
            "status IN ('Not Started', 'In Progress', 'Review', 'Completed', 'Blocked')",
            name='check_status_values'
        )
    )

    task_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.project_id'))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    start_date: Mapped[datetime] = mapped_column(DateTime)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    objectives: Mapped[List[str]] = mapped_column(
    JSON,
    default=list,
    comment="List of learning objectives for this task"
    )
    
    outcomes: Mapped[List[str]] = mapped_column(
        JSON,
        default=list,
        comment="List of expected measurable outcomes"
    )
    # Status Tracking
    status: Mapped[str] = mapped_column(String(20), default='Not Started')
    progress: Mapped[int] = mapped_column(Integer, default=0)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # GitHub Integration
    github_branch: Mapped[Optional[str]] = mapped_column(String(100))
    pr_url: Mapped[Optional[str]] = mapped_column(String(255))
    pr_state: Mapped[Optional[str]] = mapped_column(String(20))
    
    # Commit Tracking (Aggregated)
    commit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_commit_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    weekly_commit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_commit_message: Mapped[Optional[str]] = mapped_column(Text)

    # Student Contribution Tracking
    student_stats: Mapped[Dict[str, Dict]] = mapped_column(
        JSON,
        default=lambda: {},
        comment="Dict of {student_email: {commits: int, last_commit: str}}"
    )

    # Relationships
    project: Mapped['Project'] = relationship('Project', back_populates='tasks')
    assignments: Mapped[List['TaskAssignment']] = relationship(
        'TaskAssignment', 
        back_populates='task',
        cascade='all, delete-orphan'
    )
    commits: Mapped[List['TaskCommit']] = relationship(
        back_populates='task',
        cascade='all, delete-orphan',
        order_by='TaskCommit.timestamp.desc()'
    )
    
    # Add these relationships for dependencies
    dependencies: Mapped[List['TaskDependency']] = relationship(
        'TaskDependency',
        foreign_keys='TaskDependency.task_id',
        back_populates='task'
    )
    depended_on_by: Mapped[List['TaskDependency']] = relationship(
        'TaskDependency',
        foreign_keys='TaskDependency.depends_on_id',
        back_populates='depends_on'
    )
    
    @property
    def branch_pattern(self):
        return f"task-{self.task_id}-"
    


    def get_langchain_report_data(self) -> dict:
        """Format data for LangChain weekly reports"""
        return {
            'task_id': self.task_id,
            'name': self.name,
            'status': self.status,
            'progress': self.progress,
            'github_data': {
                'branch': self.github_branch,
                'pr_status': self.pr_state,
                'total_commits': self.commit_count,
                'weekly_commits': self.weekly_commit_count,
                'last_activity': self.last_commit_time.isoformat() if self.last_commit_time else None
            },
            'student_contributions': [
                {
                    'email': email,
                    'commits': stats['commits'],
                    'last_active': stats['last_commit']
                }
                for email, stats in self.student_stats.items()
            ]
        }

    
    def _extract_files_from_diff(self, diff: str) -> List[str]:
        """Helper to parse filenames from git diff"""
        if not diff:
            return []
            
        files = set()
        for line in diff.split('\n'):
            if line.startswith('+++ b/') or line.startswith('--- a/'):
                file_path = line[6:]  # Remove prefix
                if file_path not in {'/dev/null', None}:
                    files.add(file_path)
        return list(files)

class TaskDependency(Base):
    __tablename__ = 'task_dependencies'
    
    task_id: Mapped[int] = mapped_column(
        ForeignKey('tasks.task_id'), 
        primary_key=True
    )
    depends_on_id: Mapped[int] = mapped_column(
        ForeignKey('tasks.task_id'), 
        primary_key=True
    )
    
    # Relationships
    task: Mapped['Task'] = relationship(
        'Task',
        foreign_keys=[task_id],
        back_populates='dependencies'
    )
    depends_on: Mapped['Task'] = relationship(
        'Task',
        foreign_keys=[depends_on_id],
        back_populates='depended_on_by'
    )
class ProjectEvaluation(Base):
    __tablename__ = 'project_evaluations'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('groups.group_id'))
    evaluator_id: Mapped[int] = mapped_column(ForeignKey('teachers.id'))
    evaluation_date: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    # Rubric scores (stored as JSON)
    scores: Mapped[Dict[str, float]] = mapped_column(JSON, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationships
    group: Mapped['Groups'] = relationship('Groups', back_populates='evaluations')
    evaluator: Mapped['Teacher'] = relationship('Teacher')
    
class RepoDetails(Base):
    __tablename__ = 'repo_details'
    __table_args__ = (
        UniqueConstraint('group_id', name='uq_repo_group_id'),
        # Any other table args...
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('groups.group_id'))
    github_repo_url: Mapped[str] = mapped_column(String(255))
    github_repo_id: Mapped[int] = mapped_column(Integer)
    repo_access_token: Mapped[Optional[str]] = mapped_column(String(255))
    preferred_branch: Mapped[str] = mapped_column(String(50), default='main')
    repo_privacy: Mapped[str] = mapped_column(String(50), default='public')
    
    # Relationships
    group: Mapped['Groups'] = relationship('Groups', back_populates='repo_details')
    @property
    def decrypted_token(self):
        from group_dashboard.github_utils import decrypt_token
        return decrypt_token(self.repo_access_token)
class FSLSMResult(Base):
    __tablename__ = 'fslsm_results'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'), unique=True)
    active_reflective: Mapped[int] = mapped_column(Integer)
    sensing_intuitive: Mapped[int] = mapped_column(Integer)
    visual_verbal: Mapped[int] = mapped_column(Integer)
    sequential_global: Mapped[int] = mapped_column(Integer)
    
    # Relationships
    student: Mapped['Student'] = relationship('Student', back_populates='fslsm_result')
    
    
# Add these classes to models.py

class Teacher(Base):
    __tablename__ = 'teachers'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationships
    assigned_subjects: Mapped[List['TeacherSubject']] = relationship('TeacherSubject', back_populates='teacher')
    assignments: Mapped[List['Assignment']] = relationship('Assignment', back_populates='teacher')

class TeacherSubject(Base):
    __tablename__ = 'teacher_subjects'
    
    teacher_id: Mapped[int] = mapped_column(ForeignKey('teachers.id'), primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(default=False)
    
    # Relationships
    teacher: Mapped['Teacher'] = relationship('Teacher', back_populates='assigned_subjects')
    subject: Mapped['Subject'] = relationship('Subject', back_populates='teacher_associations')
    

# Update the Subject class to include teacher relationship
class Subject(Base):
    __tablename__ = 'subjects'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    credits: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(default=True)
    
    # Relationships
    student_associations: Mapped[List['StudentSubject']] = relationship('StudentSubject', back_populates='subject')
    teacher_associations: Mapped[List['TeacherSubject']] = relationship('TeacherSubject', back_populates='subject')
    assignments: Mapped[List['Assignment']] = relationship('Assignment', back_populates='subject')


    
    def get_submission_for_student(self, student_id: int) -> Optional['AssignmentSubmission']:
        """Get a specific student's submission"""
        return self.submissions.filter_by(student_id=student_id).first()
    
    def to_dict(self, include_relationships: bool = False) -> dict:
        """Convert assignment to dictionary"""
        data = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
            'due_date': self.due_date.isoformat(),
            'max_points': self.max_points,
            'is_published': self.is_published,
            'submissions_count': self.submissions_count,
            'is_past_due': self.is_past_due,
        }
        
        if include_relationships:
            data.update({
                'teacher': self.teacher.name,
                'subject': self.subject.name,
                'submissions': [sub.to_dict() for sub in self.submissions]
            })
        
        return data

class QuizAttempt(Base):
    """Tracks student attempts at quizzes"""
    __tablename__ = 'quiz_attempts'
    __table_args__ = (
        Index('ix_quiz_attempt_status', 'status'),
        Index('ix_quiz_attempt_assignment_student', 'assignment_id', 'student_id'),
    )
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey('assignments.id'),
        index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey('students.id'),
        index=True
    )
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    quiz_file: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='generating')
    progress: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    questions_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    topics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    answers: Mapped[Dict[str, str]] = mapped_column(
        JSON,
        default=dict,
        comment="Student's answers {question_id: answer}"
    )
    
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    results: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        comment="Detailed results {question_id: {correct: bool, points: float}}"
    )
    
    # Relationships
    assignment: Mapped['Assignment'] = relationship(
        'Assignment',
        back_populates='quiz_attempts',
        lazy='joined'
    )
    student: Mapped['Student'] = relationship('Student', back_populates='quiz_attempts')
    status: Mapped[str] = mapped_column(
    String(20), 
    default='generating',
    nullable=False,
    comment="Status: generating, ready, in_progress, completed, expired"
    )
    
    # Add new field
    time_spent: Mapped[Optional[int]] = mapped_column(
        Integer, 
        nullable=True,
        comment="Time spent on quiz in seconds"
    )
    version: Mapped[int] = mapped_column(
    Integer, 
    default=1,
    nullable=False,
    comment="Version number of the quiz attempt"
    )
    
    archived: Mapped[bool] = mapped_column(
        Boolean, 
        default=False,
        nullable=False,
        comment="If this attempt has been replaced"
    )

    # Type-safe access
    @property
    def quiz_assignment(self) -> Optional['QuizAssignment']:
        """Get the QuizAssignment if this is a quiz attempt"""
        return self.assignment if isinstance(self.assignment, QuizAssignment) else None

    @property
    def quiz_file_path(self) -> Optional[str]:
        if not self.quiz_file:
            return None
        return os.path.join(current_app.instance_path, 'quizzes', self.quiz_file)

    def validate_question_count(self) -> bool:
        """Verify the questions_count matches the actual CSV"""
        if not self.quiz_file_path or not os.path.exists(self.quiz_file_path):
            return False
        try:
            df = pd.read_csv(self.quiz_file_path)
            return self.questions_count == len(df)
        except:
            return False



class AssignmentSubmission(Base):
    __tablename__ = 'assignment_submissions'
    __table_args__ = (
        CheckConstraint('grade >= 0 AND grade <= 100', name='check_grade_range'),
        # Removed problematic timestamp constraint
    )
    submission_type: Mapped[str] = mapped_column(String(50), default="General")
    __mapper_args__ = {
        "polymorphic_on": submission_type,
        "polymorphic_identity": "General"
    }
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey('assignments.id', ondelete="CASCADE"),
        index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey('students.id', ondelete="CASCADE"),
        index=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,  # Remove the lambda and timezone
        server_default=func.now(),
        index=True
    )
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attachment_path: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True
    )
    grade: Mapped[Optional[float]] = mapped_column(
        Float(precision=2),
        nullable=True
    )
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default='submitted',
        nullable=False
    )
    graded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    feedback_read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    late_penalty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Relationships (unchanged)
    assignment: Mapped['Assignment'] = relationship(
        'Assignment', 
        back_populates='submissions',
        lazy='joined'
    )
    student: Mapped['Student'] = relationship(
        'Student',
        back_populates='assignment_submissions',
        lazy='joined'
    )
    attachments: Mapped[List['SubmissionAttachment']] = relationship(
        'SubmissionAttachment',
        back_populates='submission',
        cascade='all, delete-orphan'
    )

    @property
    def is_late(self) -> bool:
        """Check if submission was late"""
        if not self.assignment or not self.submitted_at:
            return False
        return self.submitted_at > self.assignment.due_date

    @property
    def final_grade(self) -> Optional[float]:
        """Calculate final grade with late penalty"""
        if self.grade is None:
            return None
        if self.late_penalty and self.is_late:
            return max(0, self.grade * (1 - self.late_penalty))
        return self.grade

    @hybrid_property
    def is_graded(self) -> bool:
        return self.status == 'graded' and self.grade is not None

    def to_dict(self, include_relationships: bool = False) -> dict:
        """Convert submission to dictionary"""
        data = {
            'id': self.id,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'status': self.status,
            'grade': self.grade,
            'final_grade': self.final_grade,
            'is_late': self.is_late,
            'attempt_number': self.attempt_number
        }
        
        if include_relationships:
            data.update({
                'student_name': self.student.name,
                'assignment_title': self.assignment.title,
                'attachments': [att.to_dict() for att in self.attachments] if self.attachments else []
            })
        
        return data
# In models.py - Add this after other submission classes
class QuizSubmission(AssignmentSubmission):
    """Specialized submission type for quizzes"""
    __tablename__ = 'quiz_submissions'
    __mapper_args__ = {"polymorphic_identity": "quiz_submission"}
    
    id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("assignment_submissions.id"),
        primary_key=True,
    )
    
    # Renamed from metadata to avoid conflict
    quiz_data: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        comment="Quiz-specific data (attempt ID, timing, etc)"
    )
    
    @property
    def related_attempt(self) -> Optional['QuizAttempt']:
        """Get associated quiz attempt"""
        return self.quiz_data.get('quiz_attempt_id') 
class AssignmentAttachment(Base):
    __tablename__ = 'assignment_attachments'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey('assignments.id'))
    filename: Mapped[str] = mapped_column(String(255))
    filepath: Mapped[str] = mapped_column(String(1024))
    uploaded_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    assignment: Mapped['Assignment'] = relationship('Assignment', back_populates='attachments')
class Assignment(Base):
    __tablename__ = 'assignments'
    __mapper_args__ = {
        'polymorphic_on': 'assignment_type',
        'polymorphic_identity': 'General',
    }
    __table_args__ = (
        CheckConstraint('max_points >= 0', name='check_max_points_positive'),
        CheckConstraint('due_date > created_at', name='check_due_after_creation'),
    )
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey('teachers.id'), index=True, nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assignment_type: Mapped[str] = mapped_column(String(50), default="General")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    max_points: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_published: Mapped[bool] = mapped_column(default=False, nullable=False)
    allow_late_submissions: Mapped[bool] = mapped_column(default=False, nullable=False)
    late_submission_penalty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    auto_grade: Mapped[bool] = mapped_column(default=False, nullable=False)
    complexity_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    # Relationships
    teacher: Mapped['Teacher'] = relationship('Teacher', back_populates='assignments')
    subject: Mapped['Subject'] = relationship('Subject', back_populates='assignments')
    submissions: Mapped[List['AssignmentSubmission']] = relationship(
        'AssignmentSubmission', 
        back_populates='assignment',
        cascade='all, delete-orphan',
        lazy='selectin'
    )
    attachments: Mapped[List['AssignmentAttachment']] = relationship(
        'AssignmentAttachment',
        back_populates='assignment',
        cascade='all, delete-orphan'
    )
    quiz_attempts: Mapped[List['QuizAttempt']] = relationship(
        'QuizAttempt',
        back_populates='assignment',
        cascade='all, delete-orphan'
    )
    # Hybrid properties
    @hybrid_property
    def submissions_count(self) -> int:
        """Count of submissions for this assignment"""
        if hasattr(self, 'submissions'):
            if isinstance(self.submissions, list):  # Eager-loaded list
                return len(self.submissions)
            return self.submissions.count()  # Dynamic query
        return 0
    
    @submissions_count.expression
    def submissions_count(cls):
        """SQL expression for submissions count"""
        return (
            select(func.count(AssignmentSubmission.id))
            .where(AssignmentSubmission.assignment_id == cls.id)
            .label('submissions_count')
        )
    
    @hybrid_property
    def is_past_due(self) -> bool:
        """Check if assignment is past due date"""
        return datetime.utcnow() > self.due_date
    
    @is_past_due.expression
    def is_past_due(cls) -> bool:
        """SQL expression for past due check"""
        return datetime.utcnow() > cls.due_date
    @property
    def submissions_query(self):
        return self.query(AssignmentSubmission).filter_by(assignment_id=self.id)
    
    @property
    def submission_rate(self) -> float:
        """Calculate submission percentage (0-100)"""
        if not hasattr(self, 'total_students') or self.total_students == 0:
            return 0.0
        return (self.submissions_count / self.total_students) * 100
    
    @property
    def average_grade(self) -> Optional[float]:
        """Calculate average grade from submissions"""
        if not self.submissions_count or not any(sub.grade for sub in self.submissions):
            return None
        return sum(
            sub.grade for sub in self.submissions 
            if sub.grade is not None
        ) / self.submissions_count
        
class QuizAssignment(Assignment):
    """Specialized assignment for quizzes"""
    __tablename__ = 'quiz_assignments'
    __mapper_args__ = {"polymorphic_identity": "Quiz"}
    
    id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("assignments.id"),
        primary_key=True,
        nullable=False,
    )
    
    # Quiz configuration
    questions: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        comment="Template questions (not student answers)"
    )
    
    question_order: Mapped[str] = mapped_column(
        String(20),
        default='random',
        nullable=False,
        comment="'fixed' or 'random' question order"
    )
    
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="Maximum allowed attempts"
    )
    
    show_correct_answers: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether to show correct answers after submission"
    )

    # No need for quiz_attempts relationship - inherited from Assignment

    @property
    def active_attempts(self) -> List[QuizAttempt]:
        """Get all non-expired quiz attempts"""
        return [a for a in self.quiz_attempts 
               if a.status in ('generating', 'in_progress')]
    
class DebuggingAssignment(Assignment):
    """Model for debugging assignments"""
    __tablename__ = 'debugging_assignments'
    __mapper_args__ = {
        'polymorphic_identity': 'Debugging'
    }
    
    id: Mapped[int] = mapped_column(ForeignKey('assignments.id'), primary_key=True)
    
    # Problem description with errors
    buggy_code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The initial code containing bugs"
    )
    
    # Expected correct output
    expected_output: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The correct output that should be produced"
    )
    
    # Error cases to identify
    known_errors: Mapped[List[Dict[str, str]]] = mapped_column(
            JSON,
            default=lambda: [],            # ⬅️  avoid shared mutable list
            comment="List of known error patterns to detect"
    )
    
    # Language/framework specific
    language: Mapped[str] = mapped_column(
        String(20),
        default='python',
        nullable=False,
        comment="Programming language of the debugging exercise"
    )
    
    # Difficulty level
    difficulty: Mapped[str] = mapped_column(
        String(20),
        default='medium',
        nullable=False,
        comment="Difficulty level (easy/medium/hard)"
    )
    
    # Time limit in minutes
    time_limit: Mapped[int] = mapped_column(
        Integer,
        default=30,
        nullable=False,
        comment="Time limit in minutes for completion"
    )
    
    # Relationship to submissions
    submissions: Mapped[List['DebuggingSubmission']] = relationship(
        'DebuggingSubmission',
        back_populates='assignment',
        cascade='all, delete-orphan',
        overlaps="assignment"
    )
    
    @property
    def error_count(self) -> int:
        """Return the number of known errors in the buggy code"""
        return len(self.known_errors)
    
    def validate_solution(self, submitted_code: str) -> Dict:
        """
        Validate a debugging solution submission
        Returns dict with keys: 'passed', 'errors_found', 'feedback'
        """
        # Implementation would depend on your execution environment
        return {
            'passed': False,
            'errors_found': 0,
            'feedback': 'Validation not implemented'
        }
class CodingAssignment(Assignment):
    __tablename__ = 'coding_assignments'
    __mapper_args__ = {
        'polymorphic_identity': 'Coding'
    }
    
    id: Mapped[int] = mapped_column(
        ForeignKey('assignments.id'), 
        primary_key=True
    )
    
    # Programming configuration
    language_options: Mapped[List[str]] = mapped_column(
        JSON,
        default=lambda: ["python", "javascript", "java"],  # Ensure default list
        server_default='["python", "javascript", "java"]',  # Add DB-level default
        nullable=False
    )
    
    starter_code: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Initial code template provided to students"
    )
    
    # Test case management
    test_cases: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        comment="Visible test cases with input/output pairs"
    )
    
    hidden_test_cases: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        comment="Hidden test cases for server-side validation"
    )
    
    # Execution constraints
    time_limit_seconds: Mapped[int] = mapped_column(
        Integer,
        default=3600,  # Default to 1 hour
        server_default='3600',  # Database-level default
        nullable=False
    )

    memory_limit_mb: Mapped[int] = mapped_column(
        Integer,
        default=512,
        server_default='512',
        nullable=False
    )
    
    # Scoring configuration
    visible_weight: Mapped[float] = mapped_column(
        Float,
        default=0.7,
        nullable=False,
        comment="Weight for visible test cases in scoring"
    )
    
    hidden_weight: Mapped[float] = mapped_column(
        Float,
        default=0.3,
        nullable=False,
        comment="Weight for hidden test cases in scoring"
    )
    
    # Execution environment
    required_libraries: Mapped[List[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        comment="Python packages/Javascript libraries required"
    )
    
    # Style/quality checks
    enable_linting: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether to perform code style checking"
    )
    
    @property
    def total_test_cases(self) -> int:
        """Get combined count of all test cases"""
        return len(self.test_cases) + len(self.hidden_test_cases)
    
    def validate_language(self, language: str) -> bool:
        """Check if a language is allowed for this assignment"""
        return language in self.language_options
    
    def to_execution_payload(self) -> Dict:
        """Convert to payload for code execution service"""
        return {
            'time_limit': self.time_limit_seconds,
            'memory_limit': self.memory_limit_mb,
            'test_cases': self.test_cases,
            'hidden_cases': self.hidden_test_cases,
            'libraries': self.required_libraries
        }
    def generate_test_cases(self):
        """Generate test cases using LLM with enhanced validation"""
        try:
            if self.test_cases and self.hidden_test_cases:
                current_app.logger.info("Test cases already exist, skipping generation")
                return

            current_app.logger.info(f"Generating test cases for assignment {self.id}")
            
            # Get the first language or default to python
            lang = self.language_options[0] if self.language_options else 'python'
            
            response = testcase_chain.invoke({
                "description": self.description,
                "language": lang
            })
            if not self.language_options:
                self.language_options = ["python"]
            current_app.logger.debug(f"Raw LLM response: {response}")
            
            generated = parse_testcases(response)
            current_app.logger.debug(f"Parsed test cases: {generated}")

            # Validate structure
            if not isinstance(generated.get("visible", []), list):
                raise ValueError("Invalid visible test cases format")
            if not isinstance(generated.get("hidden", []), list):
                raise ValueError("Invalid hidden test cases format")

            # Add IDs and validate test cases
            for i, tc in enumerate(generated["visible"]):
                tc["id"] = f"visible_{i+1}"
                if not all(k in tc for k in ("input", "expected_output")):
                    raise ValueError(f"Missing keys in visible test case {i+1}")

            for i, tc in enumerate(generated["hidden"]):
                tc["id"] = f"hidden_{i+1}"
                if not all(k in tc for k in ("input", "expected_output")):
                    raise ValueError(f"Missing keys in hidden test case {i+1}")

            self.test_cases = generated["visible"]
            self.hidden_test_cases = generated["hidden"]
            self.starter_code = generated.get("starter_code", "")
            
            current_app.logger.info(f"Generated {len(self.test_cases)} visible and {len(self.hidden_test_cases)} hidden test cases")

        except Exception as e:
            current_app.logger.error(f"Test case generation failed: {str(e)}")
            # Set default fallback test cases
            self.test_cases = [{
                "id": "default_1",
                "input": "5 3",
                "expected_output": "8",
                "explanation": "Sample addition test case"
            }]
            self.hidden_test_cases = [{
                "id": "hidden_1",
                "input": "10 20",
                "expected_output": "30"
            }]
            self.starter_code = "# Error generating starter code\n# Please implement your solution here"
            raise  # Re-raise after setting fallbacks

# Specialized submission model for coding assignments
class CodingSubmission(AssignmentSubmission):
    __tablename__ = 'coding_submissions'
    __mapper_args__ = {"polymorphic_identity": "coding_submission"}
    
    id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("assignment_submissions.id"),
        primary_key=True,
    )
    
    # Execution results
    execution_metrics: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        comment="Performance metrics (time/memory usage)"
    )
    
    # Quality analysis
    code_quality: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=True,
        comment="Code quality metrics (complexity, style)"
    )
    
    # Renamed from 'metadata' to avoid SQLAlchemy conflict
    submission_data: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        comment="All submission metadata including test results"
    )
    
    # Relationships
    assignment: Mapped['CodingAssignment'] = relationship(
        'CodingAssignment',
        foreign_keys="AssignmentSubmission.assignment_id",
        overlaps="submissions"
    )
    
    @property
    def language(self) -> str:
        """Get the programming language used"""
        return self.submission_data.get('language', 'unknown')
    
    @property
    def visible_test_results(self) -> Dict:
        """Get visible test case results"""
        return {
            'passed': self.submission_data.get('stats', {}).get('visible_passed', 0),
            'total': self.submission_data.get('stats', {}).get('total_visible', 0)
        }
    
    @property
    def hidden_test_results(self) -> Dict:
        """Get hidden test case results"""
        return {
            'passed': self.submission_data.get('stats', {}).get('hidden_passed', 0),
            'total': self.submission_data.get('stats', {}).get('total_hidden', 0)
        }

class DescriptiveAssignment(Assignment):
    """Model for descriptive/textual assignments (essays, reports, etc.)"""
    __tablename__ = 'descriptive_assignments'
    
    id: Mapped[int] = mapped_column(
        ForeignKey('assignments.id'), 
        primary_key=True
    )
    
    # Word count requirements
    min_words: Mapped[int] = mapped_column(
        Integer,
        default=300,
        nullable=False,
        comment="Minimum required word count"
    )
    
    max_words: Mapped[int] = mapped_column(
        Integer,
        default=1000,
        nullable=False,
        comment="Maximum allowed word count"
    )
    
    # Formatting requirements
    allowed_formats: Mapped[List[str]] = mapped_column(
        JSON,
        default=lambda: ["pdf", "docx", "txt"],
        comment="Allowed file formats for submissions"
    )
    
    # Grading rubric
    rubric: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        default=lambda: [
            {
                "criteria": "Content Quality",
                "description": "Depth of analysis, relevance to topic, and factual accuracy",
                "weight": 0.4,
                "levels": [
                    {"score": 90, "description": "Exceptional depth and insight, goes beyond requirements"},
                    {"score": 80, "description": "Thorough analysis, meets all requirements"},
                    {"score": 70, "description": "Adequate coverage but lacks depth"},
                    {"score": 60, "description": "Minimal coverage of key points"},
                    {"score": 50, "description": "Incomplete or off-topic content"}
                ]
            },
            {
                "criteria": "Organization & Structure",
                "description": "Logical flow, paragraph structure, and coherence",
                "weight": 0.3,
                "levels": [
                    {"score": 90, "description": "Excellent organization with smooth transitions"},
                    {"score": 80, "description": "Clear structure with minor organizational issues"},
                    {"score": 70, "description": "Basic structure but some disjointed sections"},
                    {"score": 60, "description": "Weak organization, hard to follow"},
                    {"score": 50, "description": "No apparent structure"}
                ]
            },
            {
                "criteria": "Language & Style",
                "description": "Grammar, vocabulary, tone, and academic style",
                "weight": 0.2,
                "levels": [
                    {"score": 90, "description": "Flawless grammar and sophisticated style"},
                    {"score": 80, "description": "Strong writing with minor grammatical errors"},
                    {"score": 70, "description": "Adequate but with noticeable grammatical issues"},
                    {"score": 60, "description": "Frequent errors that hinder comprehension"},
                    {"score": 50, "description": "Severe language problems throughout"}
                ]
            },
            {
                "criteria": "Originality & Critical Thinking",
                "description": "Unique insights, independent thought, and creativity",
                "weight": 0.1,
                "levels": [
                    {"score": 90, "description": "Highly original with exceptional critical analysis"},
                    {"score": 80, "description": "Shows independent thought and good analysis"},
                    {"score": 70, "description": "Some original ideas but mostly conventional"},
                    {"score": 60, "description": "Minimal original thought"},
                    {"score": 50, "description": "Completely derivative content"}
                ]
            }
        ],
        comment="Detailed grading rubric with scoring levels"
    )
    
    # Sample solution (optional)
    sample_solution: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Example high-quality response"
    )
    
    # Relationships
    submissions: Mapped[List['DescriptiveSubmission']] = relationship(
        back_populates='assignment',
        cascade='all, delete-orphan',
        overlaps="assignment"
    )
    
    __mapper_args__ = {
        'polymorphic_identity': 'Descriptive'
    }
    
    @property
    def word_count_range(self) -> str:
        """Formatted word count requirement"""
        return f"{self.min_words}-{self.max_words} words"
    
    def validate_format(self, filename: str) -> bool:
        """Check if file format is allowed"""
        ext = filename.split('.')[-1].lower()
        return ext in self.allowed_formats


class DescriptiveSubmission(AssignmentSubmission):
    """Student submissions for descriptive assignments"""
    __tablename__ = 'descriptive_submissions'
    __mapper_args__ = {"polymorphic_identity": "descriptive_submission"}
    
    id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("assignment_submissions.id"),
        primary_key=True,
    )
    
    
    word_count: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Calculated word count"
    )
    
    # AI evaluation metrics
    ai_feedback: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Automated feedback from AI analysis"
    )
    
    # Relationships
    assignment: Mapped['DescriptiveAssignment'] = relationship(
        'DescriptiveAssignment',
        back_populates='submissions',
        overlaps="submissions"
    )
    
    @property
    def descriptive_mode(self) -> str:
        """Returns either 'text' or 'file'"""
        return 'text' if self.content else 'file'
    
    def calculate_word_count(self) -> int:
        """Calculate word count from content or file"""
        if self.content:
            return len(self.content.split())
        # Implement file word count extraction if needed
        return 0

class DebuggingSubmission(AssignmentSubmission):
    """Student submissions for debugging assignments"""
    __tablename__ = 'debugging_submissions'
    __mapper_args__ = {"polymorphic_identity": "debugging_submission"}
    
    id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("assignment_submissions.id"),
        primary_key=True,
    )
    
    corrected_code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The student's corrected code"
    )
    
    errors_fixed: Mapped[List[Dict[str, str]]] = mapped_column(
        JSON,
        default=list,
        comment="List of errors the student claims to have fixed"
    )
    
    # Relationship with explicit foreign key
    assignment: Mapped["DebuggingAssignment"] = relationship(
            "DebuggingAssignment",
            back_populates="submissions",
            foreign_keys="AssignmentSubmission.assignment_id",
            overlaps="submissions",
    )

    @property
    def is_complete(self) -> bool:
        """Check if submission contains all required fields"""
        return bool(self.corrected_code and self.errors_fixed)


class SubmissionAttachment(Base):
    __tablename__ = 'submission_attachments'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey('assignment_submissions.id'))
    filename: Mapped[str] = mapped_column(String(255))
    filepath: Mapped[str] = mapped_column(String(1024))
    file_type: Mapped[str] = mapped_column(String(50))
    size: Mapped[int] = mapped_column(Integer)  # in bytes
    
    submission: Mapped['AssignmentSubmission'] = relationship(
        'AssignmentSubmission', 
        back_populates='attachments',
        enable_typechecks=False,
    )

