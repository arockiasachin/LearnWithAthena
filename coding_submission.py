from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash, session, current_app
from models import CodingAssignment, AssignmentSubmission, Student, CodingSubmission
from database import db_session
from datetime import datetime
import json
import os
from werkzeug.utils import secure_filename
from code_execution import execute_code

coding_bp = Blueprint('coding', __name__, url_prefix='/coding')

@coding_bp.route('/<int:assignment_id>', methods=['GET', 'POST'])
def coding_assessment(assignment_id):
    """Handle coding assignment viewing and submission"""
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))

    try:
        # Get assignment with enhanced error handling
        assignment = db_session.query(CodingAssignment).get(assignment_id)
        if not assignment:
            flash('Assignment not found', 'error')
            return redirect(url_for('student.view_assignments'))
            
        if not assignment.is_published:
            flash('This assignment is not currently available', 'warning')
            return redirect(url_for('student.view_assignments'))

        # Verify student enrollment
        student = db_session.get(Student, session['student_id'])
        if not student:
            flash('Student not found', 'error')
            return redirect(url_for('auth.student_login'))
            
        if not any(ss.subject_id == assignment.subject_id for ss in student.subject_associations):
            flash('You are not enrolled in this subject', 'danger')
            return redirect(url_for('student.view_assignments'))

        # Generate test cases with improved validation
        if not assignment.test_cases or not assignment.hidden_test_cases:
            current_app.logger.info(f"Generating test cases for assignment {assignment_id}")
            try:
                assignment.generate_test_cases()
                db_session.commit()
            except Exception as e:
                db_session.rollback()
                current_app.logger.error(f"Test case generation failed: {str(e)}")
                # Enhanced default test cases
                assignment.test_cases = [{
                    "id": "default_1",
                    "input": "5",
                    "expected_output": "120",
                    "explanation": "Factorial of 5"
                }]
                assignment.hidden_test_cases = [{
                    "id": "hidden_1", 
                    "input": "10",
                    "expected_output": "3628800"
                }]
                assignment.starter_code = "# Default starter code\n# Implement your solution here"
                db_session.commit()

        if request.method == 'POST':
            return handle_code_submission(assignment, student)
            
        return render_coding_interface(assignment, student)

    except Exception as e:
        db_session.rollback()
        current_app.logger.error(f"Error in coding assessment: {str(e)}", exc_info=True)
        flash('An error occurred while loading the assignment', 'danger')
        return redirect(url_for('student.view_assignments'))

def handle_code_submission(assignment, student):
    """Process code submission with enhanced test case handling"""
    try:
        current_app.logger.debug("Starting code submission process")
        code = request.form.get('code', '').strip()
        language = request.form.get('language', 'python')
        raw_test_results = request.form.get('test_results', '[]')
        
        current_app.logger.debug(f"Raw test results: {raw_test_results}")
        client_test_results = parse_test_results(raw_test_results)
        current_app.logger.debug(f"Parsed client results: {client_test_results}")

        # Validate language selection
        if language not in assignment.language_options:
            error_msg = f"Invalid language {language} not in {assignment.language_options}"
            current_app.logger.error(error_msg)
            raise ValueError(error_msg)

        current_app.logger.debug("Executing test cases...")
        execution_results = run_test_cases(
        source_code=code,
        language=language,
        test_cases=assignment.test_cases + assignment.hidden_test_cases,
        timeout=assignment.time_limit_seconds,
        memory_limit=assignment.memory_limit_mb
    )
        current_app.logger.debug(f"Initial execution results: {execution_results}")

        # Merge client-side results
        current_app.logger.debug("Merging client results...")
        for test_case in assignment.test_cases:
            client_result = next(
                (r for r in client_test_results if r.get('id') == test_case['id']),
                None
            )
            if client_result:
                current_app.logger.debug(f"Merging client result for {test_case['id']}: {client_result}")
                server_result = next(r for r in execution_results if r['id'] == test_case['id'])
                server_result.update({
                    'passed': client_result.get('passed', False),
                    'output': client_result.get('output', server_result.get('output', '')),
                    'error': client_result.get('error', server_result.get('error', '')),
                    'execution_time': client_result.get('execution_time', server_result.get('execution_time', 0))
                })

        current_app.logger.debug(f"Merged execution results: {execution_results}")

        # Calculate scores
        current_app.logger.debug("Calculating scores...")
        visible_passed = sum(1 for t in assignment.test_cases if any(r['passed'] and r['id'] == t['id'] for r in execution_results))
        hidden_passed = sum(1 for t in assignment.hidden_test_cases if any(r['passed'] and r['id'] == t['id'] for r in execution_results))
        
        current_app.logger.debug(f"Visible passed: {visible_passed}/{len(assignment.test_cases)}")
        current_app.logger.debug(f"Hidden passed: {hidden_passed}/{len(assignment.hidden_test_cases)}")

        score = calculate_final_score(
            visible_passed=visible_passed,
            total_visible=len(assignment.test_cases),
            hidden_passed=hidden_passed,
            total_hidden=len(assignment.hidden_test_cases),
            visible_weight=assignment.visible_weight,
            hidden_weight=assignment.hidden_weight
        )
        current_app.logger.debug(f"Calculated score: {score}")

        # Create submission
        current_app.logger.debug("Creating submission...")
        submission = create_submission(
            assignment=assignment,
            student=student,
            code=code,
            language=language,
            execution_results=execution_results,
            score=score,
            visible_passed=visible_passed,
            hidden_passed=hidden_passed
        )

        db_session.add(submission)
        db_session.commit()
        current_app.logger.info(f"Submission created: {submission.id}")

        return handle_submission_response(assignment.id, submission)

    except Exception as e:
        db_session.rollback()
        current_app.logger.error(f"Code submission error: {str(e)}", exc_info=True)
        return error_response(str(e), request.is_json)


def create_submission(assignment, student, code, language, execution_results, score, visible_passed, hidden_passed):
    """Create comprehensive submission record with enhanced metadata"""
    # Calculate max execution metrics
    max_time = max(r.get('execution_time', 0) for r in execution_results)
    max_memory = max(r.get('memory_used', 0) for r in execution_results)
    
    # Organize test results by visibility
    visible_results = [
        r for r in execution_results 
        if any(t['id'] == r['id'] for t in assignment.test_cases)
    ]
    hidden_results = [
        r for r in execution_results 
        if any(t['id'] == r['id'] for t in assignment.hidden_test_cases)
    ]

    return CodingSubmission(
        assignment_id=assignment.id,
        student_id=student.id,
        content=code,
        status='graded' if assignment.auto_grade else 'submitted',
        grade=score if assignment.auto_grade else None,
        execution_metrics={
            'max_time': max_time,
            'max_memory': max_memory,
            'total_tests': len(execution_results)
        },
        submission_data={  # Changed from metadata to submission_data
            'language': language,
            'environment': {
                'time_limit': assignment.time_limit_seconds,
                'memory_limit': assignment.memory_limit_mb,
                'libraries': assignment.required_libraries
            },
            'test_results': {
                'visible': visible_results,
                'hidden': hidden_results
            },
            'stats': {
                'visible_passed': visible_passed,
                'visible_total': len(assignment.test_cases),
                'hidden_passed': hidden_passed,
                'hidden_total': len(assignment.hidden_test_cases),
                'success_rate': (visible_passed + hidden_passed) / len(execution_results)
            },
            'score_breakdown': {
                'visible': (visible_passed / len(assignment.test_cases)) * assignment.visible_weight * 100,
                'hidden': (hidden_passed / len(assignment.hidden_test_cases)) * assignment.hidden_weight * 100,
                'final': score
            }
        }
    )

def calculate_final_score(visible_passed, total_visible, hidden_passed, total_hidden, visible_weight, hidden_weight):
    """Calculate weighted score with robust error handling"""
    try:
        visible_score = (visible_passed / total_visible) * visible_weight if total_visible > 0 else 0
        hidden_score = (hidden_passed / total_hidden) * hidden_weight if total_hidden > 0 else 0
        return min(100, round((visible_score + hidden_score) * 100, 2))
    except ZeroDivisionError:
        return 0

def handle_submission_response(assignment_id, submission):
    """Handle both AJAX and regular form submissions"""
    if request.is_json:
        return jsonify({
            'success': True,
            'score': submission.grade,
            'visible_passed': submission.submission_data['stats']['visible_passed'],  # Changed from metadata
            'hidden_passed': submission.submission_data['stats']['hidden_passed'],   # Changed from metadata
            'submission_id': submission.id,
            'test_results': submission.submission_data['test_results']  # Changed from metadata
        })
    
    flash('Submission successful!', 'success')
    return redirect(url_for('student.view_assignments', assignment_id=assignment_id))

def render_coding_interface(assignment, student):
    """Render coding interface with all necessary context"""
    return render_template('student/assignments/coding_assessment.html',
        assignment=assignment,
        student=student,
        languages=assignment.language_options,
        starter_code=assignment.starter_code,
        test_cases=assignment.test_cases,
        max_file_size=current_app.config.get('MAX_CODE_SUBMISSION_SIZE', 1024 * 1024)
    )

def parse_test_results(test_results):
    """Safely parse test results from JSON string"""
    try:
        parsed = json.loads(test_results) if test_results else []
        
        # Handle case where results come as object/dict
        if isinstance(parsed, dict):
            # Convert to list of test results
            return [{'id': k, **v} for k, v in parsed.items()]
            
        return parsed
    except json.JSONDecodeError:
        current_app.logger.warning("Failed to parse test results JSON")
        return []

def error_response(message, is_ajax=False):
    """Handle error responses consistently"""
    if is_ajax:
        return jsonify({
            'success': False,
            'error': str(message)
        }), 400
    
    flash(f'Submission error: {message}', 'danger')
    return redirect(request.url)

def run_test_cases(source_code, language, test_cases, timeout, memory_limit):
    """Execute and evaluate each test case individually"""
    test_results = []
    
    for case in test_cases:
        try:
            # Add newline to simulate Enter key press
            test_input = f"{case['input']}\n"
            result = execute_code(
                source_code=source_code,
                language=language,
                test_input=test_input,  # Pass formatted input
                timeout=timeout,
                memory_limit=memory_limit
            )
            
            test_results.append({
                'id': case['id'],
                'passed': result['output'] == case['expected_output'].strip(),
                'input': case['input'],
                'expected': case['expected_output'],
                'received': result['output'],
                'error': result['error'],
                'execution_time': result['metrics']['execution_time']
            })
        except Exception as e:
            print(e)
            test_results.append({
                'id': case['id'],
                'passed': False,
                'error': str(e)
            })
    
    return test_results