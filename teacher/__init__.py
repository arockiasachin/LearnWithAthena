from flask import Blueprint

teacher_bp = Blueprint('teacher', __name__, template_folder='templates')

from . import routes, assignments, groups, students, group_progress, github_reports,evaluation  