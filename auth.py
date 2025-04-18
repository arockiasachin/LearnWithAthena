from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import sqlite3
from database import init_db, db_session
from models import Student , StudentSubject, Subject, Teacher  # Add this import

auth_bp = Blueprint('auth', __name__)
DATABASE = 'CollabEdu.db'

################################
# Student Signup
################################
@auth_bp.route('/student_signup', methods=['GET', 'POST'])
def student_signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO students (name, email, password) VALUES (?, ?, ?)",
                               (name, email, password))
                conn.commit()
                flash('Student Signup Successful!', 'success')
                return redirect(url_for('auth.student_login'))
            except sqlite3.IntegrityError:
                flash('Email already registered!', 'danger')
    return render_template('student_signup.html')

################################
# Student Login
################################
@auth_bp.route('/student_login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM students WHERE email = ? AND password = ?",
                           (email, password))
            student = cursor.fetchone()
            if student:
                session['student_id'] = student[0]  # store ID
                session['student_name'] = student[1]
                return redirect(url_for('auth.student_dashboard'))
            else:
                flash('Invalid Credentials', 'danger')
    return render_template('student_login.html')

@auth_bp.route('/student_dashboard')
def student_dashboard():
    # If student is not logged in, redirect to student login
    if 'student_id' not in session:
        flash("Please log in first.", "danger")
        return redirect(url_for('auth.student_login'))

    # Student is logged in — retrieve the name from session
    student_name = session.get('student_name', 'Student')

    # Render the modern Bootstrap dashboard page
    # We'll pass the student_name to the template
    return render_template('student_dashboard.html', student_name=student_name)

# Add this new route to auth.py
@auth_bp.route('/student_courses')
def student_courses():
    if 'student_id' not in session:
        flash("Please log in first.", "danger")
        return redirect(url_for('auth.student_login'))
    
    return render_template('student_courses.html')


################################
# Teacher Signup
################################
@auth_bp.route('/teacher_signup', methods=['GET', 'POST'])
def teacher_signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        
        try:
            # Check if email already exists
            existing_teacher = db_session.query(Teacher).filter_by(email=email).first()
            if existing_teacher:
                flash('Email already registered!', 'danger')
                return redirect(url_for('auth.teacher_signup'))
            
            # Create new teacher
            teacher = Teacher(
                name=name,
                email=email,
                password=password
            )
            db_session.add(teacher)
            db_session.commit()
            
            flash('Teacher account created successfully!', 'success')
            return redirect(url_for('auth.teacher_login'))
            
        except Exception as e:
            db_session.rollback()
            flash(f'Error creating account: {str(e)}', 'danger')
    
    return render_template('teacher_signup.html')
################################
# Teacher Login
################################
@auth_bp.route('/teacher_login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        teacher = db_session.query(Teacher).filter_by(email=email, password=password).first()
        if teacher:
            session['teacher_id'] = teacher.id
            session['teacher_name'] = teacher.name
            session['is_admin'] = teacher.is_admin
            return redirect(url_for('teacher.teacher_dashboard'))
        else:
            flash('Invalid Credentials', 'danger')
    
    return render_template('teacher_login.html')

@auth_bp.route('/teacher_dashboard')
def teacher_dashboard():
    if 'teacher_id' in session:
        return f"Welcome, {session['teacher_name']}! This is the Teacher Dashboard."
    else:
        return redirect(url_for('auth.teacher_login'))


@auth_bp.route('/student/update_profile', methods=['GET', 'POST'])
def update_profile():
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    all_subjects = db_session.query(Subject).filter_by(is_active=True).all()
    
    if request.method == 'POST':
        register_number = request.form.get('register_number')
        github_username = request.form.get('github_username')
        selected_subject_ids = request.form.getlist('enrolled_subjects')
        
        try:
            student.register_number = register_number
            student.github_username = github_username
            
            # Clear existing subjects
            db_session.query(StudentSubject).filter_by(student_id=student.id).delete()
            
            # Add new subjects
            for subject_id in selected_subject_ids:
                if subject_id:
                    association = StudentSubject(
                        student_id=student.id,
                        subject_id=int(subject_id)
                    )
                    db_session.add(association)
            
            db_session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('student.student_dashboard'))
        except Exception as e:
            db_session.rollback()
            flash(f'Error updating profile: {str(e)}', 'danger')
    
    return render_template('student_profile_update.html',
                         student=student,
                         all_subjects=all_subjects)
    

    