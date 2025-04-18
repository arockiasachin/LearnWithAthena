from flask import Blueprint
from .step1 import formation_step1
from .step2 import formation_step2
from .step3 import formation_step3
from .step4 import formation_step4

formation_bp = Blueprint('formation', __name__)

formation_bp.add_url_rule('/step1', view_func=formation_step1, methods=['GET', 'POST'])
formation_bp.add_url_rule('/step2', view_func=formation_step2, methods=['GET', 'POST'])
formation_bp.add_url_rule('/step3', view_func=formation_step3, methods=['GET', 'POST'])
formation_bp.add_url_rule('/step4', view_func=formation_step4, methods=['GET', 'POST'])