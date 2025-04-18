from models import AssignmentSubmission
from database import db_session
from datetime import datetime

class AssessmentService:
    """Handles assessment submission and grading"""
    
    @staticmethod
    def create_submission(assignment_id, student_id, content, file=None):
        """Create new assessment submission"""
        submission = AssignmentSubmission(
            assignment_id=assignment_id,
            student_id=student_id,
            content=content,
            status='submitted',
            submitted_at=datetime.utcnow()
        )
        
        if file and file.filename:
            filename = secure_filename(file.filename)
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            submission.attachment_path = filename
        
        db_session.add(submission)
        db_session.commit()
        return submission

    @staticmethod
    def auto_grade(submission):
        """Auto-grade submission based on content"""
        # Implement your grading logic here
        content = submission.content or ""
        submission.grade = len(content.split()) // 10  # Example simple grading
        submission.status = 'graded'
        submission.graded_at = datetime.utcnow()
        db_session.commit()