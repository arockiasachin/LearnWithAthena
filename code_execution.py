# code_execution.py (Updated Version)
import subprocess
import tempfile
import os
import json
from datetime import datetime
import time
from flask import Blueprint, request, jsonify, current_app
from models import CodingAssignment
from database import db_session

def execute_code(source_code, language, test_input, timeout=5, memory_limit=512):
    """Executes code with security constraints and test case validation"""
    result = {
        'success': False,
        'output': '',
        'error': '',
        'metrics': {
            'execution_time': 0,
            'memory_used': 0,
            'cpu_usage': 0
        },
        'timestamp': datetime.utcnow().isoformat()
    }

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_ext = {
                'python': 'py',
                'javascript': 'js',
                'java': 'java'
            }.get(language, 'txt')
            
            file_path = os.path.join(temp_dir, f'solution_{os.urandom(8).hex()}.{file_ext}')
            
            with open(file_path, 'w') as f:
                f.write(source_code)

            commands = {
                'python': ['python', file_path],
                'javascript': ['node', file_path],
                'java': ['javac', file_path, '&&', 'java', '-cp', temp_dir, 'Solution']
            }[language]

            # Prepare input - ensure proper formatting
            input_data = test_input
            if not input_data.endswith('\n'):
                input_data += '\n'

            start_time = time.time()
            process = subprocess.run(
                ' '.join(commands),
                input=input_data,  # Remove .encode() here
                shell=True,
                capture_output=True,
                text=True,  # Keep text=True for string handling
                timeout=timeout
            )
            end_time = time.time()
            
            elapsed_time = end_time - start_time

            result.update({
                'output': process.stdout.strip(),
                'error': process.stderr,
                'success': process.returncode == 0,
                'metrics': {
                    'execution_time': round(elapsed_time, 2),
                    'memory_used': 0,
                    'cpu_usage': 0
                }
            })

    except subprocess.TimeoutExpired as e:
        end_time = time.time()
        result['error'] = f'Timeout after {timeout} seconds'
        result['metrics']['execution_time'] = round(end_time - start_time, 2)
    except Exception as e:
        result['error'] = str(e)

    return result

execution_bp = Blueprint('execution', __name__)

@execution_bp.route('/api/execute-code', methods=['POST'])
@execution_bp.route('/api/execute-code', methods=['POST'])
def execute_code_endpoint():
    """Handle both single execution and test case runs"""
    data = request.json
    current_app.logger.info(f"Execution request: {data.keys()}")

    # Single code execution (Run Code button)
    if 'test_input' in data:
        result = execute_code(
            source_code=data.get('code'),
            language=data.get('language'),
            test_input=data.get('test_input', '') + "\n",
            timeout=data.get('timeout', 5),
            memory_limit=data.get('memory_limit', 512)
        )
        return jsonify(result)

    # Visible test execution (Run Tests button)
    if 'assignment_id' in data:
        try:
            assignment = db_session.query(CodingAssignment).get(data['assignment_id'])
            if not assignment:
                return jsonify({'error': 'Assignment not found'}), 404

            # Execute only visible test cases
            results = []
            for test_case in assignment.test_cases:
                exec_result = execute_code(
                    source_code=data['code'],
                    language=data['language'],
                    test_input=f"{test_case['input']}\n",
                    timeout=assignment.time_limit_seconds,
                    memory_limit=assignment.memory_limit_mb
                )
                
                passed = (exec_result['output'].strip() == 
                         test_case['expected_output'].strip())

                results.append({
                    'test_id': test_case['id'],
                    'passed': passed,
                    'output': exec_result['output'],
                    'error': exec_result['error'],
                    'execution_time': exec_result['metrics']['execution_time']
                })

            return jsonify({'visible': results})

        except Exception as e:
            current_app.logger.error(f"Execution error: {str(e)}")
            return jsonify({'error': 'Internal server error'}), 500

    return jsonify({'error': 'Invalid request format'}), 400