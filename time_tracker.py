from datetime import datetime, timedelta
from flask import session

class TimeTracker:
    """Handles all time-related functionality for assessments"""
    
    @staticmethod
    def start_assessment(assignment_id):
        """Initialize timer when assessment begins"""
        session['assessment'] = {
            'start_time': datetime.utcnow().isoformat(),
            'assignment_id': assignment_id
        }

    @staticmethod
    def get_remaining_time(assignment):
        """Calculate remaining time in seconds"""
        if not session.get('assessment'):
            return None
            
        start_time = datetime.fromisoformat(session['assessment']['start_time'])
        elapsed = datetime.utcnow() - start_time
        remaining = timedelta(minutes=assignment.time_limit_minutes) - elapsed
        return max(0, remaining.total_seconds())

    @staticmethod
    def validate_submission_time(assignment):
        """Check if submission is within time limit"""
        if not assignment.is_timed:
            return True
            
        remaining = TimeTracker.get_remaining_time(assignment)
        return remaining is not None and remaining > 0

    @staticmethod
    def clear_timer():
        """Remove timer data from session"""
        session.pop('assessment', None)