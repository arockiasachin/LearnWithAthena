from flask import Flask, redirect, url_for,jsonify, session, flash, render_template, request
from flask_wtf.csrf import CSRFProtect
from auth import auth_bp
from FSLSM_Quiz import quiz_bp
from student_dashboard import student_bp
import quiz_generator
from group_dashboard import group_bp
from database import init_db, db_session
from models import Student
from datetime import timedelta, datetime
import os
import logging
from logging.handlers import RotatingFileHandler
from group_dashboard import init_app as init_group_dashboard
from teacher.routes import teacher_bp
from quiz_loading import quiz_loading_bp
from descriptive_submission import descriptive_bp
from student_marks import marks_bp
from timed_assessment import timed_bp
from coding_submission import coding_bp
from code_execution import execution_bp
from debugging import debugging_bp
import markdown
from markupsafe import Markup 
from bleach import clean
from config import MAX_CODE_SUBMISSION_SIZE
# In your Flask app setup
import random
from jinja2 import Environment
from apscheduler.schedulers.background import BackgroundScheduler
from group_dashboard.polling import poll_github_activity

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-123')
app.config['DEEPSEEK_API_KEY'] = os.getenv("DEEPSEEK_API_KEY")
csrf = CSRFProtect(app)
#csrf.exempt(group_bp)
init_group_dashboard(app)
def shuffle_filter(seq):
    try:
        shuffled = list(seq)
        random.shuffle(shuffled)
        return shuffled
    except:
        return seq

app.jinja_env.filters['shuffle'] = shuffle_filter
# Session configuration
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2)
)

app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')
app.config['MAX_CODE_SUBMISSION_SIZE'] = MAX_CODE_SUBMISSION_SIZE
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
if not app.debug or os.getenv('FORCE_SCHEDULER') == 'true':
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=poll_github_activity,
        args=[app],
        trigger="interval",
        minutes=30,
        id='github_polling',
        misfire_grace_time=60,
        max_instances=1
    )
    try:
        scheduler.start()
        app.logger.info("GitHub polling scheduler started successfully")
    except Exception as e:
        app.logger.error(f"Failed to start scheduler: {str(e)}")
# Configure logging
def configure_logging():
    # Create logs directory if it doesn't exist
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Create a rotating file handler
    file_handler = RotatingFileHandler(
        f'{log_dir}/app.log',
        maxBytes=1024 * 1024 * 10,  # 10MB
        backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    
    # Add handler to the app logger
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    
    # Log startup message
    app.logger.info('Application startup')

configure_logging()
from datetime import datetime

@app.context_processor
def inject_now():
    return {'now': datetime.now}
# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(student_bp, url_prefix='/student')
app.register_blueprint(teacher_bp, url_prefix='/teacher')
app.register_blueprint(quiz_loading_bp)
app.register_blueprint(descriptive_bp, url_prefix='/descriptive')
app.register_blueprint(marks_bp, url_prefix='/student')
app.register_blueprint(timed_bp)
app.register_blueprint(coding_bp, url_prefix='/coding')
app.register_blueprint(execution_bp)
app.register_blueprint(debugging_bp, url_prefix='/debugging')


def markdown_to_html(text):
    if not text:
        return ""
    unsafe_html = markdown.markdown(text)
    safe_html = clean(unsafe_html)  # Remove dangerous HTML
    return Markup(safe_html)

app.jinja_env.filters['markdown'] = markdown_to_html
# Request logging middleware
@app.before_request
def log_request_info():
    # Skip logging for static files
    if request.path.startswith('/static/'):
        return
    
    # Log request details
    app.logger.info(
        f"Request: {request.method} {request.path} | "
        f"IP: {request.remote_addr} | "
        f"User-Agent: {request.user_agent} | "
        f"Params: {request.args.to_dict()} | "
        f"Form: {request.form.to_dict()}"
    )

# Response logging middleware
@app.after_request
def log_response_info(response):
    # Skip logging for static files
    if request.path.startswith('/static/'):
        return response
    
    # Log response details
    app.logger.info(
        f"Response: {request.method} {request.path} -> "
        f"Status: {response.status_code} | "
        f"Size: {response.content_length} bytes | "
        f"User: {session.get('student_id', 'Anonymous')}"
    )
    return response

@app.route('/student/<reg_num>/details')
def student_details(reg_num):
    student = db_session.query(Student).filter_by(register_number=reg_num).first()
    if not student:
        app.logger.warning(f"Student not found: {reg_num}")
        return jsonify({'error': 'Student not found'})
    
    subjects = [s.subject.name for s in student.subject_associations]
    
    app.logger.info(f"Accessed student details: {reg_num}")
    return jsonify({
        'name': student.name,
        'avatar': student.github_avatar,
        'subjects': subjects
    })

@app.context_processor
def inject_template_vars():
    context = {
        'is_logged_in': 'student_id' in session,
        'current_route': request.endpoint if request.endpoint else None
    }
    
    if 'student_id' in session:
        student = db_session.get(Student, session['student_id'])
        context.update({
            'current_student': student,
            'has_group': bool(student.groups) if student else False
        })
    return context

@app.route('/')
def home():
    app.logger.info("Accessed home page")
    return render_template('home.html')

@app.route('/logout')
def logout():
    user_id = session.get('student_id', 'Anonymous')
    session.clear()
    flash('Logged out successfully', 'success')
    app.logger.info(f"User logged out: {user_id}")
    return redirect(url_for('home'))

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    app.logger.warning(f"404 Not Found: {request.url}")
    return render_template('errors/404.html'), 404

@app.errorhandler(403)
def forbidden(e):
    app.logger.warning(f"403 Forbidden: {request.url}")
    return render_template('errors/403.html'), 403

@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"500 Internal Server Error: {request.url}\n{str(e)}")
    return render_template('errors/500.html'), 500
@app.teardown_appcontext
def shutdown_session(exc=None):
    db_session.remove()
if __name__ == '__main__':
    init_db()
    app.logger.info("Starting application in debug mode")
    app.run(debug=True)