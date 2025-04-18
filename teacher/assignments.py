from flask import render_template, request, flash, redirect, url_for, send_from_directory, session, current_app
from datetime import date, datetime
from . import teacher_bp
from database import db_session
from models import Assignment, Teacher, Subject, TeacherSubject, Student,DescriptiveAssignment, DebuggingAssignment, QuizAssignment, CodingAssignment  
from .utils import generate_course_schedule
from datetime import datetime
import pandas as pd
import os
import logging
from sqlalchemy import or_
import traceback
from sqlalchemy.orm import with_polymorphic
import io
from testcase_functions import testcase_chain, parse_testcases

# Configure logging
logger = logging.getLogger(__name__)

@teacher_bp.route('/assignment_management', methods=['GET', 'POST'])
def assignment_management():
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    teacher = db_session.get(Teacher, session['teacher_id'])
    teacher_subjects = db_session.query(Subject).join(TeacherSubject).filter(
        TeacherSubject.teacher_id == teacher.id
    ).all()
    
    if request.method == 'POST':
        return handle_post_request(teacher, teacher_subjects)
    
    schedule_files = get_schedule_files(teacher)
    assignments = get_filtered_assignments(teacher)
    total_students = db_session.query(Student).count()
    return render_template(
        'teacher/teacher_assignment_management.html',
        teacher=teacher,
        teacher_subjects=teacher_subjects,
        assignments=assignments,
        schedule_files=schedule_files,
        total_students=total_students,
        current_date=date.today(),
        current_filters={
            'subject': request.args.get('subject'),
            'type': request.args.get('type')
        }
    )

def handle_post_request(teacher, teacher_subjects):
    """Handle POST requests for assignment management"""
    if 'create_assignment' in request.form:
        return handle_create_assignment(teacher)
    elif 'schedule_course' in request.form:
        return handle_schedule_course(teacher, teacher_subjects)
    return redirect(url_for('teacher.assignment_management'))

def handle_create_assignment(teacher):
    """Handle creation of a new assignment with polymorphic support"""
    try:
        title = request.form.get('title')
        description = request.form.get('description')
        due_date = request.form.get('due_date')
        subject_id = request.form.get('subject_id')
        is_published = request.form.get('is_published') == 'on'
        assignment_type = request.form.get('assignment_type', 'General')
        
        if not all([title, due_date, subject_id]):
            raise ValueError("All required fields must be filled")
        
        # Create appropriate subclass instance
        if assignment_type == 'Coding':
            new_assignment = CodingAssignment(
                title=title,
                description=description,
                due_date=datetime.strptime(due_date, '%Y-%m-%d'),
                teacher_id=teacher.id,
                subject_id=subject_id,
                is_published=is_published,
                time_limit_seconds=int(request.form.get('time_limit_seconds', 3600)),
                language_options=request.form.get('language_options', 'python').split(','),
                starter_code=request.form.get('starter_code', '')
            )
        elif assignment_type == 'Quiz':
            new_assignment = QuizAssignment(
                title=title,
                description=description,
                due_date=datetime.strptime(due_date, '%Y-%m-%d'),
                teacher_id=teacher.id,
                subject_id=subject_id,
                is_published=is_published,
                max_attempts=int(request.form.get('max_attempts', 1)),
                show_correct_answers=request.form.get('show_answers') == 'on'
            )
        elif assignment_type == 'Debugging':
            new_assignment = DebuggingAssignment(
                title=title,
                description=description,
                due_date=datetime.strptime(due_date, '%Y-%m-%d'),
                teacher_id=teacher.id,
                subject_id=subject_id,
                is_published=is_published,
                buggy_code=request.form.get('buggy_code', ''),
                expected_output=request.form.get('expected_output', '')
            )
        elif assignment_type == 'Descriptive':
            new_assignment = DescriptiveAssignment(
                title=title,
                description=description,
                due_date=datetime.strptime(due_date, '%Y-%m-%d'),
                teacher_id=teacher.id,
                subject_id=subject_id,
                is_published=is_published,
                min_words=int(request.form.get('min_words', 300)),
                max_words=int(request.form.get('max_words', 1000))
            )
        else:
            new_assignment = Assignment(
                title=title,
                description=description,
                due_date=datetime.strptime(due_date, '%Y-%m-%d'),
                teacher_id=teacher.id,
                subject_id=subject_id,
                is_published=is_published
            )
        
        db_session.add(new_assignment)
        db_session.commit()
        flash(f'{assignment_type} assignment created successfully!', 'success')
        print(f'{assignment_type} assignment created successfully!', 'success')
        
    except ValueError as e:
        db_session.rollback()
        flash(f"Validation error: {str(e)}", 'danger')
        print(f"Validation error: {str(e)}", 'danger')
    except Exception as e:
        db_session.rollback()
        flash(f"Error creating assignment: {str(e)}", 'danger')
        print(f"Error creating assignment: {str(e)}", 'danger')
        current_app.logger.error(f"Assignment creation failed:\n{traceback.format_exc()}")
    
    return redirect(url_for('teacher.assignment_management'))

def get_filtered_assignments(teacher):
    """Get assignments with polymorphic loading and optional filters"""
    # Load all assignment types polymorphically
    Assignment_poly = with_polymorphic(Assignment, [CodingAssignment, QuizAssignment, 
                                                  DebuggingAssignment, DescriptiveAssignment])
    assignments_query = db_session.query(Assignment_poly).filter(
        Assignment_poly.teacher_id == teacher.id
    )
    
    # Apply filters if present
    if request.args.get('subject'):
        assignments_query = assignments_query.filter(
            Assignment_poly.subject_id == request.args.get('subject')
        )
    if request.args.get('type'):
        assignments_query = assignments_query.filter(
            Assignment_poly.assignment_type == request.args.get('type')
        )
    
    return assignments_query.order_by(Assignment_poly.due_date.desc()).all()


def handle_schedule_course(teacher, teacher_subjects):
    """Handle course schedule generation"""
    try:
        subject_id = request.form.get('subject_id')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        syllabus_text = request.form.get('syllabus_text')
        
        if not all([subject_id, start_date, end_date, syllabus_text]):
            raise ValueError("All schedule fields are required")
        
        subject = db_session.get(Subject, subject_id)
        if not subject:
            raise ValueError("Invalid subject selected")
        
        # Validate dates
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        if start > end:
            raise ValueError("End date must be after start date")
        if (end - start).days < 7:
            raise ValueError("Schedule must cover at least 1 week")
        
        # Generate schedule
        result = generate_course_schedule(
            syllabus_text=syllabus_text,
            start_date=start_date,
            end_date=end_date,
            subject_id=subject_id,
            subject_name=subject.name
        )
        
        # Save CSV file
        schedules_dir = os.path.join(current_app.root_path, 'static', 'schedules')
        csv_path = os.path.join(schedules_dir, result['filename'])
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write(result['csv_content'])
        
        flash(
            f"Schedule generated with {len(result['schedule'])} assignments "
            f"from {start_date} to {end_date}", 
            'success'
        )
        
        schedule_files = get_schedule_files(teacher)
        return render_template(
            'teacher/teacher_assignment_management.html',
            teacher=teacher,
            teacher_subjects=teacher_subjects,
            assignments=get_filtered_assignments(teacher),
            schedule_files=schedule_files,
            generated_schedule=result['schedule'],
            new_schedule_filename=result['filename']
        )
        
    except ValueError as e:
        flash(f"Validation error: {str(e)}", 'danger')
        return redirect(url_for('teacher.assignment_management'))
    except Exception as e:
        flash(f"Schedule generation failed: {str(e)}", 'danger')
        logger.error(f"Schedule generation failed: {str(e)}", exc_info=True)
        return redirect(url_for('teacher.assignment_management'))
    
    #return redirect(url_for('teacher.assignment_management'))

def get_schedule_files(teacher):
    """Get all schedule files for the teacher"""
    schedule_files = []
    schedules_dir = os.path.join(current_app.root_path, 'static', 'schedules')
    os.makedirs(schedules_dir, exist_ok=True)
    
    for f in os.listdir(schedules_dir):
        if f.endswith('_schedule.csv'):  # Updated pattern to match new format
            try:
                parts = f.split('_')
                if len(parts) >= 2:  # Ensure filename has subject_id
                    subject_id = parts[0]  # First part is subject_id
                    subject = db_session.get(Subject, subject_id)
                    
                    # Only show files for subjects this teacher teaches
                    if subject and any(ts.subject_id == int(subject_id) for ts in teacher.assigned_subjects):
                        schedule_files.append({
                            'filename': f,
                            'subject': subject.name,
                            'subject_id': subject_id,
                            'created_at': datetime.fromtimestamp(
                                os.path.getmtime(os.path.join(schedules_dir, f))
                            ).strftime('%Y-%m-%d %H:%M'),
                            'size': os.path.getsize(os.path.join(schedules_dir, f))
                        })
            except Exception as e:
                logger.error(f"Error processing schedule file {f}: {str(e)}")
    
    return schedule_files

def get_filtered_assignments(teacher):
    """Get assignments with optional filters applied"""
    assignments_query = db_session.query(Assignment).filter(
        Assignment.teacher_id == teacher.id
    )
    
    # Apply filters if present
    if request.args.get('subject'):
        assignments_query = assignments_query.filter(
            Assignment.subject_id == request.args.get('subject')
        )
    if request.args.get('type'):
        assignments_query = assignments_query.filter(
            Assignment.assignment_type == request.args.get('type')
        )
    
    return assignments_query.order_by(Assignment.due_date.desc()).all()


@teacher_bp.route('/schedules/<filename>')
def view_schedule(filename):
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    # Enhanced security check
    if (not filename.endswith('_schedule.csv') or 
        '..' in filename or 
        '/' in filename):
        flash('Access denied', 'danger')
        return redirect(url_for('teacher.assignment_management'))
    
    schedules_dir = os.path.join(current_app.root_path, 'static', 'schedules')
    try:
        return send_from_directory(
            schedules_dir,
            filename,
            as_attachment=False,
            mimetype='text/csv'
        )
    except Exception as e:
        flash(f"Could not retrieve schedule: {str(e)}", 'danger')
        return redirect(url_for('teacher.assignment_management'))
    

@teacher_bp.route('/import_schedule/<filename>', methods=['POST'])
def import_schedule(filename):
    if 'teacher_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.teacher_login'))
    
    # Security validation
    if (not filename.endswith('.csv') or '..' in filename or '/' in filename):
        flash('Access denied', 'danger')
        return redirect(url_for('teacher.assignment_management'))

    csv_path = os.path.join(current_app.root_path, 'static', 'schedules', filename)
    
    if not os.path.exists(csv_path):
        flash('Schedule file not found', 'danger')
        return redirect(url_for('teacher.assignment_management'))

    try:
        # Read and clean the CSV file
        with open(csv_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        
        cleaned_content = clean_csv(raw_content)
        
        # Parse with pandas
        schedule_df = pd.read_csv(io.StringIO(cleaned_content))
        
        # Validate structure
        required_columns = [
            'Week', 'Module Number', 'Module Title',
            'Assignment Type', 'Assignment Title',
            'Due Date', 'Description'
        ]
        if not all(col in schedule_df.columns for col in required_columns):
            raise ValueError(f"CSV missing required columns. Found: {schedule_df.columns.tolist()}")
        
        # Process assignments
        teacher_id = session['teacher_id']
        subject_id = filename.split('_')[0]
        assignments = []
        skipped_rows = 0
        
        for idx, row in schedule_df.iterrows():
            try:
                # Skip rows with missing required fields
                if pd.isna(row['Assignment Title']) or pd.isna(row['Due Date']):
                    skipped_rows += 1
                    continue
                
                # Parse and validate date
                due_date_str = str(row['Due Date']).strip()
                try:
                    due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
                except ValueError:
                    current_app.logger.warning(f"Row {idx}: Invalid date format '{due_date_str}'")
                    skipped_rows += 1
                    continue
                
                # Create assignment dict with type-specific fields
                assignment = {
                    'title': str(row['Assignment Title']),
                    'description': str(row['Description']) if not pd.isna(row['Description']) else '',
                    'due_date': due_date,
                    'teacher_id': teacher_id,
                    'subject_id': subject_id,
                    'assignment_type': str(row.get('Assignment Type', 'General')),
                    'is_published': True
                }
                
                # Add type-specific fields
                assignment_type = assignment['assignment_type']
                if assignment_type == 'Coding':
                    assignment.update({
                        'time_limit_seconds': 3600,
                        'language_options': ['python'],
                        'starter_code': '',
                        'test_cases': [],  # Initialize empty test cases
                        'hidden_test_cases': []  # Initialize empty hidden test cases
                    })
                    try:
                        # Generate test cases for coding assignments
                        response = testcase_chain.invoke({
                            "description": assignment['description'],
                            "language": "python"
                        })
                        generated = parse_testcases(response)
                        
                        # Add IDs to test cases
                        for i, tc in enumerate(generated["visible"]):
                            tc["id"] = f"visible_{i+1}"
                        for i, tc in enumerate(generated["hidden"]):
                            tc["id"] = f"hidden_{i+1}"
                            
                        assignment.update({
                            'test_cases': generated["visible"],
                            'hidden_test_cases': generated["hidden"],
                            'starter_code': generated.get("starter_code", "")
                        })
                    except Exception as e:
                        current_app.logger.error(f"Failed to generate test cases for row {idx}: {str(e)}")
                        # Fallback to default test cases
                        assignment.update({
                            'test_cases': [{
                                "id": "default_1",
                                "input": "1 1",
                                "expected_output": "2",
                                "explanation": "Sample addition test case"
                            }],
                            'hidden_test_cases': [{
                                "id": "hidden_1",
                                "input": "10 20",
                                "expected_output": "30"
                            }],
                            'starter_code': "# Default starter code\n# Implement your solution here"
                        })
                elif assignment_type == 'Quiz':
                    assignment.update({
                        'max_attempts': 1,
                        'show_correct_answers': False
                    })
                elif assignment_type == 'Debugging':
                    assignment.update({
                        'buggy_code': '',
                        'expected_output': ''
                    })
                elif assignment_type == 'Descriptive':
                    assignment.update({
                        'min_words': 300,
                        'max_words': 1000
                    })
                
                assignments.append(assignment)
                
            except Exception as e:
                current_app.logger.error(f"Error processing row {idx}: {str(e)}")
                skipped_rows += 1
                continue
        
        # Handle existing assignments if replacing
        if request.form.get('replace_existing') == 'yes':
            deleted_count = db_session.query(Assignment).filter(
                Assignment.teacher_id == teacher_id,
                Assignment.subject_id == subject_id
            ).delete()
            db_session.commit()
        else:
            deleted_count = 0
        
        # Batch insert new assignments with proper type handling
        if assignments:
            batch_size = 50
            for i in range(0, len(assignments), batch_size):
                batch = assignments[i:i+batch_size]
                
                # Group by type for efficient bulk inserts
                type_groups = {}
                for assignment in batch:
                    type_groups.setdefault(assignment['assignment_type'], []).append(assignment)
                
                for assignment_type, group in type_groups.items():
                    if assignment_type == 'Coding':
                        db_session.bulk_insert_mappings(CodingAssignment, group)
                    elif assignment_type == 'Quiz':
                        db_session.bulk_insert_mappings(QuizAssignment, group)
                    elif assignment_type == 'Debugging':
                        db_session.bulk_insert_mappings(DebuggingAssignment, group)
                    elif assignment_type == 'Descriptive':
                        db_session.bulk_insert_mappings(DescriptiveAssignment, group)
                    else:
                        db_session.bulk_insert_mappings(Assignment, group)
                
                db_session.commit()
        
        flash(
            f"Successfully imported {len(assignments)} assignments. "
            f"Skipped {skipped_rows} invalid rows. "
            f"Replaced {deleted_count} existing assignments." if deleted_count else "",
            'success'
        )
        
    except Exception as e:
        db_session.rollback()
        current_app.logger.error(f"Import failed: {str(e)}", exc_info=True)
        flash(f"Import failed: {str(e)}", 'danger')
    
    return redirect(url_for('teacher.assignment_management'))


def clean_csv(csv_content: str) -> str:
    """Robust CSV cleaner with multiple validation layers"""
    lines = [line.strip() for line in csv_content.splitlines() if line.strip()]
    
    # Remove markdown fences
    if lines and lines[0].startswith('```'):
        lines = lines[1:]
    if lines and lines[-1].startswith('```'):
        lines = lines[:-1]
    
    # Find actual header (may be after explanatory text)
    header_idx = next(
        (i for i, line in enumerate(lines) 
         if line.startswith('Week,Module Number')),
        None
    )
    
    if header_idx is None:
        raise ValueError("No valid CSV header found")
    
    lines = lines[header_idx:]
    if not lines:
        raise ValueError("No data rows found after header")
    
    # Validate header
    header = lines[0]
    expected_columns = [
        'Week', 'Module Number', 'Module Title',
        'Assignment Type', 'Assignment Title',
        'Due Date', 'Description'
    ]
    
    if not all(col in header for col in expected_columns):
        raise ValueError(f"Header missing required columns. Found: {header}")
    
    # Process data rows
    cleaned_lines = [header]
    for line in lines[1:]:
        parts = [part.strip().strip('"') for part in line.split(',')]
        
        # Skip malformed rows
        if len(parts) != len(expected_columns):
            continue
        
        # Validate date
        try:
            datetime.strptime(parts[5], '%Y-%m-%d')
            cleaned_lines.append(','.join(
                f'"{p}"' if ',' in p else p 
                for p in parts
            ))
        except ValueError:
            continue
    
    if len(cleaned_lines) < 2:
        raise ValueError("No valid data rows after cleaning")
    
    return '\n'.join(cleaned_lines)