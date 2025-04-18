# github_webhook.py
from flask import request, current_app
from database import db_session
import hmac
import hashlib
import json
import logging
from typing import Dict, Any
from group_dashboard.github_webhook_handlers import WebhookHandlers
from flask_wtf.csrf import CSRFProtect


logger = logging.getLogger(__name__)
csrf = CSRFProtect()
def verify_signature(signature: str, payload: bytes, secret: bytes) -> bool:
    """Securely verify GitHub webhook signature"""
    if not signature or not payload or not secret:
        return False
        
    try:
        hash_object = hmac.new(secret, msg=payload, digestmod=hashlib.sha256)
        expected_signature = 'sha256=' + hash_object.hexdigest()
        return hmac.compare_digest(signature, expected_signature)
    except Exception as e:
        logger.error(f"Signature verification failed: {str(e)}")
        return False

def github_webhook():
    """Handle GitHub webhook events with improved security and validation"""
    # Verify webhook signature
    signature = request.headers.get('X-Hub-Signature-256', '')
    secret = current_app.config.get('GITHUB_WEBHOOK_SECRET', '').encode()
    
    if not verify_signature(signature, request.data, secret):
        logger.warning("Invalid webhook signature received")
        return "Invalid signature", 403
    
    try:
        event = request.headers.get('X-GitHub-Event')
        payload = json.loads(request.data)
        
        if not event or not payload:
            raise ValueError("Missing event or payload")
            
        logger.info(f"Received GitHub {event} event")

        # Route to appropriate handler
        handlers = {
            'push': WebhookHandlers.handle_push_event,
            'pull_request': WebhookHandlers.handle_pr_event,
            'issues': WebhookHandlers.handle_issue_event,
            'create': WebhookHandlers.handle_branch_tag_event
        }
        
        if event in handlers:
            # For PRs, only handle closed+merged
            if event == 'pull_request' and payload.get('action') != 'closed':
                return "Ignored PR action", 200
                
            handlers[event](payload)
            
        return "OK", 200
        
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload received")
        return "Invalid payload", 400
    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}", exc_info=True)
        db_session.rollback()
        return "Server error", 500