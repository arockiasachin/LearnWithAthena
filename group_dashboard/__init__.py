from flask import Blueprint, current_app,flash,redirect,url_for

group_bp = Blueprint('group', __name__)
from group_dashboard.polling import poll_github_activity

def init_app(app):
    # Import routes here to avoid circular imports
    from . import routes, members, projects, timeline, evaluations, submissions
    from .formation import formation_bp
    from .github_webhook import github_webhook
    
    # Register routes
    group_bp.add_url_rule('/dashboard', view_func=routes.dashboard)
    group_bp.add_url_rule('/members', view_func=members.member_details)
    group_bp.add_url_rule('/projects', view_func=projects.project_details)
    group_bp.add_url_rule('/timeline', view_func=timeline.project_timeline, methods=['GET', 'POST'])  # Added methods here
    group_bp.add_url_rule('/timeline/update_task/<int:task_id>', view_func=timeline.update_task, methods=['POST'])
    group_bp.add_url_rule('/evaluations', view_func=evaluations.group_assessments)
    group_bp.add_url_rule('/submissions', view_func=submissions.submissions,methods=['GET', 'POST'])
    #group_bp.add_url_rule('/sync_github')
    #group_bp.add_url_rule('/github_webhook', view_func=github_webhook, methods=['POST'])

    # Register formation blueprint
    group_bp.register_blueprint(formation_bp, url_prefix='/formation')
    
    @group_bp.route('/sync_github')
    def manual_syncs():
        try:
            poll_github_activity(current_app)
            flash('GitHub data synchronized successfully', 'success')
        except Exception as e:
            flash(f'Sync failed: {str(e)}', 'danger')
            current_app.logger.error(f"Manual sync error: {str(e)}")
        return redirect(url_for('group.project_timeline'))
    
    @group_bp.route('/test_poll')
    def manual_sync():
        try:
            poll_github_activity(current_app)
            flash('Test polling completed', 'success')
        except Exception as e:
            flash(f'Test polling failed: {str(e)}', 'danger')
            current_app.logger.error(f"Test poll error: {str(e)}")
        return redirect(url_for('group.project_timeline'))

    # Register the main blueprint with the app
    app.register_blueprint(group_bp, url_prefix='/group')
    #app.config['GITHUB_WEBHOOK_SECRET'] = 'POMegranateWebhook2025!'
