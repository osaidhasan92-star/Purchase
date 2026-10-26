"""Same-origin Flask API and static frontend. Run schema/admin setup with Flask CLI."""
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import click
from flask import Flask, abort, g, jsonify, request, send_from_directory, send_file
from io import BytesIO
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select, update, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from .permissions import COLLECTIONS, HR_COLLECTIONS, ACTIONS, MODULES, allowed, default_roles, in_scope
from .validation import InvalidBusinessState, validate_business

db = SQLAlchemy()


@event.listens_for(Engine, 'connect')
def sqlite_constraints(connection, _record):
    if isinstance(connection, sqlite3.Connection):
        connection.execute('PRAGMA foreign_keys=ON')

ROOT = Path(__file__).resolve().parent.parent
COOKIE = 'purchase_session'
APP_KEYS = set(COLLECTIONS) | {'roles', 'company', 'users', 'activities'}
APPROVAL_STATUSES = {'Approved', 'Selected', 'Processed', 'Paid', 'Delivered'}


class User(db.Model):
    id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    role = db.Column(db.String(80), nullable=False)
    manager_id = db.Column(db.String(64), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)

    def public(self):
        return dict(id=self.id, name=self.name, email=self.email, role=self.role,
                    managerId=self.manager_id, active=self.active)


class LoginSession(db.Model):
    token_hash = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.String(64), db.ForeignKey('user.id'), nullable=False, index=True)
    csrf = db.Column(db.String(64), nullable=False)
    expires = db.Column(db.Float, nullable=False, index=True)


class LoginAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bucket = db.Column(db.String(64), nullable=False, index=True)
    at = db.Column(db.Float, nullable=False, index=True)


class Document(db.Model):
    """Versioned business aggregates. A CAS update prevents lost concurrent writes."""
    name = db.Column(db.String(32), primary_key=True)
    data = db.Column(db.JSON, nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1)


class Audit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.String(64), nullable=False, index=True)
    action = db.Column(db.String(120), nullable=False)
    details = db.Column(db.JSON, nullable=False)
    at = db.Column(db.String(40), nullable=False)


class Attachment(db.Model):
    id = db.Column(db.String(64), primary_key=True)
    uploader_id = db.Column(db.String(64), nullable=False)
    module = db.Column(db.String(80), nullable=False)
    filename = db.Column(db.String(254), nullable=False)
    content = db.Column(db.LargeBinary, nullable=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def problem(message, status=400):
    abort(status, description=message)


def body():
    data = request.get_json()
    if not isinstance(data, dict):
        problem('Expected a JSON object')
    return data


def audit(action, details=None):
    db.session.add(Audit(actor_id=g.user.id if getattr(g, 'user', None) else 'system',
                         action=action, details=details or {}, at=utcnow()))


def app_document():
    doc = db.session.get(Document, 'app')
    if not doc:
        problem('Run flask --app backend.app init-db before starting the server', 503)
    return doc


def require_admin():
    if g.user.role != 'Admin':
        problem('Administrator access required', 403)


def check_password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 256:
        problem('Password must contain between 12 and 256 characters')


def validate_json(value, path='state'):
    """Reject non-finite values, credential injection, and unreasonable nesting."""
    if path.count('.') > 18:
        problem('Record is nested too deeply')
    if isinstance(value, float) and not math.isfinite(value):
        problem('Numbers must be finite')
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in ('password', 'password_hash', 'initialpassword', 'currentpassword', 'newpassword'):
                problem('Credentials may only be submitted to account endpoints')
            validate_json(item, path + '.' + key)
    elif isinstance(value, list):
        for item in value:
            validate_json(item, path + '.item')


def records(value):
    if not isinstance(value, list) or any(not isinstance(r, dict) or r.get('id') is None for r in value):
        problem('Collections must contain records with IDs')
    keys = [str(r['id']) for r in value]
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key) for key in keys):
        problem('Record IDs must be letters, numbers, underscores or hyphens')
    if len(set(keys)) != len(keys):
        problem('Duplicate record IDs')
    return {str(r['id']): r for r in value}


def visible_state(doc):
    state = deepcopy(doc.data)
    user = g.user
    # User profiles are needed for ownership selectors; credentials never leave the account table.
    profiles = db.session.scalars(select(User)).all()
    if user.role != 'Admin':
        profiles = [u for u in profiles if u.id == user.id or u.role == 'Sales Manager' or
                    (user.role == 'Sales Manager' and u.manager_id == user.id)]
    state['users'] = [u.public() for u in profiles]
    for key, module in COLLECTIONS.items():
        state[key] = [r for r in state.get(key, []) if allowed(user, doc.data, module) and in_scope(user, r, key, doc.data)]
    state['activities'] = []
    if allowed(user, doc.data, 'activities'):
        entries = db.session.scalars(select(Audit).order_by(Audit.id.desc()).limit(2000)).all()
        if user.role != 'Admin':
            entries = [entry for entry in entries if entry.actor_id == user.id]
        state['activities'] = [dict(id=a.id, userId=a.actor_id, userName=a.actor_id,
                                    action=a.action, module='Server', details=json.dumps(a.details),
                                    createdAt=a.at) for a in entries]
    return state


def merge_collection(key, incoming, existing, state, module):
    """Merge only the caller's visible rows, preserving hidden rows and checking actions."""
    old = records(existing)
    new = records(incoming)
    visible = {rid: r for rid, r in old.items() if in_scope(g.user, r, key, state)}
    for rid in set(new) | set(visible):
        before, after = visible.get(rid), new.get(rid)
        if before == after:
            continue
        if rid in old and rid not in visible:
            problem('Record is outside your assigned scope', 403)
        action = 'create' if before is None else 'delete' if after is None else 'edit'
        if not allowed(g.user, state, module, action):
            problem(f'Permission denied: {module}.{action}', 403)
        if after and key == 'payroll':
            previous, target = (before or {}).get('status'), after.get('status')
            if previous != target and target not in {None:{'Draft'},'Draft':{'Approved'},'Approved':{'Paid'},'Paid':set()}.get(previous,set()):
                problem('Payroll must progress from Draft to Approved to Paid')
        if after and key == 'salesQuotations':
            stages = {None: {'Draft', 'Pending Approval'}, 'Draft': {'Pending Approval', 'Rejected'},
                      'Pending Approval': {'Approved', 'Rejected'}, 'Approved': {'Sent'},
                      'Sent': {'Accepted', 'Rejected', 'Expired'}, 'Accepted': {'Converted'},
                      'Rejected': set(), 'Expired': set(), 'Converted': set()}
            previous, target = (before or {}).get('status'), after.get('status')
            if previous != target and target not in stages.get(previous, set()):
                problem('Invalid sales quotation status transition')
        if after and before is None and key == 'customers' and g.user.role in ('Sales Manager', 'Salesperson', 'Sales Representative'):
            after['ownerId'] = g.user.id
            after['managerId'] = g.user.id if g.user.role == 'Sales Manager' else g.user.manager_id
        if after and not in_scope(g.user, after, key, state):
            # New customers may be created by sales staff, then linked to a new lead.
            if not (key == 'customers' and before is None):
                problem('Record is outside your assigned scope', 403)
        if after and after.get('status') != (before or {}).get('status') and after.get('status') in APPROVAL_STATUSES:
            # Sales staff can record completed physical deliveries; financial approvals remain restricted.
            if not (key == 'deliveries') and not allowed(g.user, state, module, 'approve'):
                problem(f'Approval permission required: {module}', 403)
        if after:
            validate_numbers(after)
        if after and before and key == 'salesQuotations' and after.get('status') == 'Approved' and g.user.role != 'Admin':
            if g.user.role != 'Sales Manager' or str(before.get('managerId')) != g.user.id:
                problem('Only the assigned Sales Manager can approve this quotation', 403)
    hidden = [r for rid, r in old.items() if rid not in visible]
    return list(new.values()) + hidden


def validate_numbers(record):
    nonnegative = {'amount', 'quantity', 'rate', 'quotedRate', 'total', 'salary', 'basic',
                   'allowances', 'deductions', 'netPay', 'receivedQty', 'acceptedQty',
                   'rejectedQty', 'deliveredQty', 'finalSettlement', 'shippingCharges'}
    for key, value in record.items():
        if (key == 'id' or key.endswith('Id')) and value is not None and value != '' and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(value)):
            problem('Invalid record identifier')
        if key in nonnegative and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or not math.isfinite(value)):
            problem(f'{key} must be a finite non-negative number')
        if key in ('taxPercent', 'discountPercent') and (not isinstance(value, (int, float)) or not 0 <= value <= 100):
            problem(f'{key} must be between 0 and 100')
        if isinstance(value, dict):
            validate_numbers(value)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    validate_numbers(row)


def validate_company(company):
    if company.get('currency', 'PKR') != 'PKR' or company.get('country', 'Pakistan') != 'Pakistan':
        problem('This single-company demo is fixed to Pakistan and PKR')
    logo = company.get('logo')
    if logo and not (isinstance(logo, str) and (
            re.fullmatch(r'data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=\s]+', logo) or
            re.fullmatch(r'(assets/)?[A-Za-z0-9_-]+\.(png|jpe?g|webp|gif)', logo))):
        problem('Logo must be a raster image')
    website = company.get('website')
    if website and (not isinstance(website, str) or urlsplit(website).scheme not in ('https', 'http')):
        problem('Company website must start with https:// or http://')


def commit_document(doc, revision, data):
    if not isinstance(revision, int) or isinstance(revision, bool):
        problem('An integer revision is required', 428)
    from .erp import lock, sync_business
    lock()
    previous = deepcopy(doc.data)
    result = db.session.execute(update(Document).where(Document.name == doc.name, Document.revision == revision)
                                .values(data=data, revision=revision + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.session.rollback()
        problem('Another user saved newer data. Reload before trying again.', 409)
    sync_business(previous, data, doc.name)
    audit('Saved ' + doc.name, {'collections': sorted(g.changed_keys)})
    db.session.commit()
    return revision + 1


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    uri = os.environ.get('DATABASE_URL', 'sqlite:///' + str(ROOT / 'instance' / 'purchase.sqlite'))
    if uri.startswith('postgresql://'):
        uri = uri.replace('postgresql://', 'postgresql+psycopg://', 1)
    (ROOT / 'instance').mkdir(exist_ok=True)
    app.config.update(SQLALCHEMY_DATABASE_URI=uri, SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      MAX_CONTENT_LENGTH=12 * 1024 * 1024, COOKIE_SECURE=os.environ.get('COOKIE_SECURE', 'true').lower() == 'true',
                      PUBLIC_ORIGIN=os.environ.get('PUBLIC_ORIGIN', ''), SESSION_HOURS=8)
    if config:
        app.config.update(config)
    db.init_app(app)

    @app.before_request
    def authenticate():
        if not request.path.startswith('/api/') or request.path in ('/api/health', '/api/auth/login'):
            return
        token = request.cookies.get(COOKIE, '')
        session = db.session.get(LoginSession, digest(token)) if token else None
        user = db.session.get(User, session.user_id) if session and session.expires > time.time() else None
        if not user or not user.active:
            problem('Please sign in again', 401)
        g.user, g.login_session = user, session
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.csrf):
                problem('Invalid CSRF token', 403)
            check_origin()

    def check_origin():
        origin = request.headers.get('Origin')
        expected = app.config['PUBLIC_ORIGIN'].rstrip('/') or request.host_url.rstrip('/')
        if origin and origin.rstrip('/') != expected:
            problem('Cross-origin request rejected', 403)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(IntegrityError)
    def integrity_error(error):
        db.session.rollback()
        return jsonify(error='A record with that identifier already exists'), 409

    @app.errorhandler(InvalidBusinessState)
    def invalid_business(error):
        db.session.rollback()
        return jsonify(error=str(error)), 400

    @app.get('/api/health')
    def health():
        db.session.execute(select(1))
        return jsonify(ok=True)

    @app.post('/api/auth/login')
    def login():
        check_origin()
        data = body()
        email, password = str(data.get('email', '')).strip().lower(), data.get('password', '')
        if not isinstance(password, str) or len(password) > 256:
            problem('Invalid email or password', 401)
        # Persistent limits work across workers. Use the direct peer IP; never trust arbitrary X-Forwarded-For.
        buckets = [digest('email:' + email), digest('ip:' + (request.remote_addr or 'unknown'))]
        cutoff = time.time() - 900
        for index, bucket in enumerate(buckets):
            count = db.session.query(LoginAttempt).filter(LoginAttempt.bucket == bucket, LoginAttempt.at > cutoff).count()
            if count >= (10 if index == 0 else 100):
                problem('Too many sign-in attempts. Try again in 15 minutes.', 429)
        user = db.session.scalar(select(User).where(User.email == email))
        if not user or not user.active or not check_password_hash(user.password_hash, password):
            for bucket in buckets:
                db.session.add(LoginAttempt(bucket=bucket, at=time.time()))
            db.session.query(LoginAttempt).filter(LoginAttempt.at < cutoff).delete()
            db.session.commit()
            problem('Invalid email or password', 401)
        db.session.query(LoginAttempt).filter(LoginAttempt.bucket == buckets[0]).delete()
        old = request.cookies.get(COOKIE)
        if old:
            db.session.query(LoginSession).filter_by(token_hash=digest(old)).delete()
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.session.add(LoginSession(token_hash=digest(token), user_id=user.id, csrf=csrf,
                                    expires=time.time() + app.config['SESSION_HOURS'] * 3600))
        db.session.query(LoginSession).filter(LoginSession.expires < time.time()).delete()
        g.user = user
        audit('Signed in')
        db.session.commit()
        response = jsonify(user=user.public(), csrfToken=csrf)
        response.set_cookie(COOKIE, token, httponly=True, secure=app.config['COOKIE_SECURE'], samesite='Lax',
                            max_age=app.config['SESSION_HOURS'] * 3600, path='/')
        return response

    @app.get('/api/auth/me')
    def me():
        return jsonify(user=g.user.public(), csrfToken=g.login_session.csrf)

    @app.post('/api/auth/logout')
    def logout():
        db.session.delete(g.login_session)
        audit('Signed out')
        db.session.commit()
        response = jsonify(ok=True)
        response.delete_cookie(COOKIE, path='/', secure=app.config['COOKIE_SECURE'], httponly=True, samesite='Lax')
        return response

    @app.post('/api/auth/change-password')
    def change_password():
        data = body()
        current = data.get('currentPassword', '')
        if not isinstance(current, str) or not check_password_hash(g.user.password_hash, current):
            problem('Current password is incorrect')
        new = data.get('newPassword')
        check_password(new)
        if new != data.get('confirmPassword') or new == current:
            problem('New passwords must match and differ from the current password')
        g.user.password_hash = generate_password_hash(new)
        db.session.query(LoginSession).filter_by(user_id=g.user.id).delete()
        audit('Changed password')
        db.session.commit()
        response = jsonify(ok=True, signInRequired=True)
        response.delete_cookie(COOKIE, path='/')
        return response

    @app.route('/api/users', methods=['GET', 'POST'])
    @app.route('/api/users/<user_id>', methods=['PUT'])
    @app.post('/api/users/<user_id>/password')
    def users(user_id=None):
        require_admin()
        if request.method == 'GET':
            return jsonify(users=[u.public() for u in db.session.scalars(select(User)).all()])
        data = body()
        user = db.session.get(User, user_id) if user_id else None
        if user_id and not user:
            problem('User not found', 404)
        if request.path.endswith('/password'):
            password = data.get('password')
            check_password(password)
            if password != data.get('confirmPassword'):
                problem('Passwords must match')
            user.password_hash = generate_password_hash(password)
        else:
            role = str(data.get('role', ''))
            if role not in app_document().data['roles']:
                problem('Unknown role')
            email, name = str(data.get('email', '')).strip().lower(), str(data.get('name', '')).strip()
            if not name or len(name) > 160 or '@' not in email or len(email) > 254:
                problem('A valid name and email are required')
            manager_id = data.get('managerId') or None
            if manager_id:
                manager = db.session.get(User, str(manager_id))
                if not manager or not manager.active or manager.role != 'Sales Manager':
                    problem('Select an active Sales Manager')
            if role in ('Salesperson', 'Sales Representative') and not manager_id:
                problem('A Sales Manager is required')
            active = data.get('active', True)
            if not isinstance(active, bool):
                problem('active must be a boolean')
            if user and user.id == g.user.id and (not active or role != 'Admin'):
                problem('You cannot disable or demote your own administrator account')
            password = data.get('password')
            if not user:
                check_password(password)
                user = User(id='user-' + secrets.token_hex(12), password_hash=generate_password_hash(password))
                db.session.add(user)
            elif password:
                check_password(password)
                user.password_hash = generate_password_hash(password)
            user.name, user.email, user.role, user.manager_id, user.active = name, email, role, manager_id, active
        if user_id:
            db.session.query(LoginSession).filter_by(user_id=user.id).delete()
        audit('Updated account' if user_id else 'Created account', {'userId': user.id})
        db.session.commit()
        return jsonify(user.public())

    @app.route('/api/state', methods=['GET', 'PATCH'])
    def state():
        doc = app_document()
        if request.method == 'GET':
            return jsonify(state=visible_state(doc), revision=doc.revision)
        data = body()
        changes = data.get('changes')
        if not isinstance(changes, dict) or set(changes) - APP_KEYS:
            problem('Unknown or invalid state collections')
        validate_json(changes)
        saved = deepcopy(doc.data)
        g.changed_keys = set(changes) - {'users', 'activities'}
        for key, incoming in changes.items():
            if key in ('users', 'activities'):
                continue  # Profiles and audit events are managed by the server.
            if key == 'roles':
                require_admin()
                if not isinstance(incoming, dict) or set(incoming) != set(saved['roles']):
                    problem('Roles must retain the configured role names')
                for role in incoming.values():
                    if not isinstance(role, dict):
                        problem('Invalid role')
                    perms = role.get('permissions', {})
                    if not isinstance(perms, dict) or set(perms) - set(MODULES):
                        problem('Invalid permission modules')
                    for values in perms.values():
                        if not isinstance(values, dict) or set(values) - set(ACTIONS) or any(not isinstance(v, bool) for v in values.values()):
                            problem('Permissions must be boolean actions')
                saved[key] = incoming
            elif key == 'company':
                if not allowed(g.user, doc.data, 'settings', 'edit'):
                    problem('Company settings permission required', 403)
                if not isinstance(incoming, dict):
                    problem('Invalid company settings')
                validate_company(incoming)
                saved[key] = incoming
            else:
                saved[key] = merge_collection(key, incoming, saved.get(key, []), doc.data, COLLECTIONS[key])
        validate_business(saved)
        revision = commit_document(doc, data.get('revision'), saved)
        return jsonify(ok=True, revision=revision)

    @app.route('/api/hr/state', methods=['GET', 'PATCH'])
    def hr_state():
        doc, state = db.session.get(Document, 'hr'), app_document().data
        if request.method == 'GET':
            filtered = {key: value if allowed(g.user, state, module) else [] for key, module in HR_COLLECTIONS.items()
                        for value in [deepcopy(doc.data.get(key, []))]}
            return jsonify(state=filtered, revision=doc.revision)
        data = body()
        changes = data.get('changes')
        if not isinstance(changes, dict) or set(changes) - set(HR_COLLECTIONS):
            problem('Unknown HR collections')
        validate_json(changes)
        saved = deepcopy(doc.data)
        g.changed_keys = set(changes)
        for key, incoming in changes.items():
            saved[key] = merge_collection(key, incoming, saved.get(key, []), state, HR_COLLECTIONS[key])
        revision = commit_document(doc, data.get('revision'), saved)
        return jsonify(ok=True, revision=revision)

    @app.get('/api/admin/export')
    def export():
        require_admin()
        state = deepcopy(app_document().data)
        state['users'] = [u.public() for u in db.session.scalars(select(User)).all()]
        return jsonify(format=1, exportedAt=utcnow(), app=state,
                       hr=db.session.get(Document, 'hr').data,
                       users=state['users'])

    @app.post('/api/admin/import')
    def import_demo():
        require_admin()
        data = body()
        app_doc, hr_doc = app_document(), db.session.get(Document, 'hr')
        if any(app_doc.data.get(k) for k in COLLECTIONS) or any(hr_doc.data.values()):
            problem('Import is only available for an empty installation', 409)
        incoming, hr = data.get('app', {}), data.get('hr', {})
        if not isinstance(incoming, dict) or not isinstance(hr, dict):
            problem('Invalid import')
        saved = deepcopy(app_doc.data)
        for key in COLLECTIONS:
            value = incoming.get(key, [])
            records(value)
            validate_json(value)
            for row in value:
                validate_numbers(row)
            saved[key] = value
        if isinstance(incoming.get('company'), dict):
            validate_json(incoming['company'])
            validate_company(incoming['company'])
            saved['company'] = incoming['company']
        hr_saved = {key: hr.get(key, []) for key in HR_COLLECTIONS}
        for value in hr_saved.values():
            records(value)
            validate_json(value)
            for row in value:
                validate_numbers(row)
        # Preserve referenced user IDs without importing any browser passwords.
        for profile in incoming.get('users', []):
            uid = str(profile.get('id', ''))
            if not uid or db.session.get(User, uid):
                continue
            role = profile.get('role', 'Viewer')
            email = str(profile.get('email', '')).lower().strip()
            if role not in saved['roles'] or '@' not in email:
                problem('Imported user has invalid role or email')
            db.session.add(User(id=uid, name=str(profile.get('name', email)), email=email, role=role,
                                manager_id=profile.get('managerId'), active=False,
                                password_hash=generate_password_hash(secrets.token_urlsafe(32))))
        validate_business(saved)
        app_doc.data, hr_doc.data = saved, hr_saved
        app_doc.revision += 1
        hr_doc.revision += 1
        audit('Imported browser records')
        db.session.commit()
        return jsonify(ok=True, message='Records imported. Reset passwords and activate imported users before use.')

    @app.get('/api/admin/audit')
    def audit_log():
        require_admin()
        before = request.args.get('before', type=int)
        query = select(Audit).order_by(Audit.id.desc()).limit(200)
        if before:
            query = query.where(Audit.id < before)
        rows = db.session.scalars(query).all()
        return jsonify(events=[dict(id=a.id, actorId=a.actor_id, action=a.action, details=a.details, at=a.at) for a in rows])

    @app.post('/api/attachments')
    def upload_attachment():
        module = request.form.get('module')
        if module not in ('requests', 'quotations', 'orders', 'expenses') or not allowed(g.user, app_document().data, module, 'create'):
            problem('Attachment upload permission required', 403)
        file = request.files.get('file')
        if not file:
            problem('Select a PDF file')
        content = file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024 or not content.startswith(b'%PDF-'):
            problem('Upload a PDF of at most 10 MB')
        attachment = Attachment(id=secrets.token_hex(16), uploader_id=g.user.id, module=module,
                                filename=secure_filename(file.filename or 'document.pdf') or 'document.pdf', content=content)
        db.session.add(attachment)
        audit('Uploaded attachment', {'attachmentId': attachment.id, 'module': module})
        db.session.commit()
        return jsonify(name=attachment.filename, attachmentPath=attachment.id)

    @app.get('/api/attachments/<attachment_id>')
    @app.get('/api/quotation-attachments/<attachment_id>')
    def download_attachment(attachment_id):
        attachment = db.session.get(Attachment, attachment_id)
        if not attachment:
            abort(404)
        state = app_document().data
        if not allowed(g.user, state, attachment.module):
            problem('Attachment access denied', 403)
        linked = any(r.get('attachmentPath') == attachment_id and in_scope(g.user, r, key, state)
                     for key, module in COLLECTIONS.items() if module == attachment.module for r in state.get(key, []))
        if attachment.module == 'expenses':
            from .erp import Expense
            linked = bool(db.session.scalar(select(Expense.id).where(Expense.attachment_id == attachment_id))) and allowed(g.user, state, 'expenses', 'approve')
        if g.user.role != 'Admin' and attachment.uploader_id != g.user.id and not linked:
            problem('Attachment access denied', 403)
        return send_file(BytesIO(attachment.content), mimetype='application/pdf',
                         download_name=attachment.filename, as_attachment=True)

    @app.get('/')
    def index():
        return send_from_directory(ROOT, 'index.html')

    @app.get('/<path:path>')
    def frontend(path):
        if path in ('bootstrap.html', 'seed.html', 'settings.html'):
            problem('Demo login shortcuts have been removed', 410)
        # Never expose backend source, environment files, database files or backup JS.
        public = {'app.js', 'crm.js', 'sales.js', 'sales_patch.js', 'hr.js', 'backend-client.js', 'erp.js', 'erp.css',
                  'shared.css', 'styles.css', 'logo.png', 'dexterra-stamp.jpg'}
        pages = {p.name for p in ROOT.glob('*.html')} - {'bootstrap.html', 'seed.html'}
        asset = path.startswith('assets/') and Path(path).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
        if path not in public | pages and not asset:
            abort(404)
        return send_from_directory(ROOT, path)

    @app.cli.command('init-db')
    def init_db():
        """Create the initial schema and empty company (run once before workers start)."""
        db.create_all()
        if not db.session.get(Document, 'app'):
            state = {key: [] for key in COLLECTIONS}
            state.update(roles=default_roles(), company={}, users=[], activities=[])
            db.session.add(Document(name='app', data=state, revision=1))
        if not db.session.get(Document, 'hr'):
            db.session.add(Document(name='hr', data={key: [] for key in HR_COLLECTIONS}, revision=1))
        db.session.flush()
        from .erp import initialize
        initialize()
        db.session.commit()
        click.echo('Database initialized; existing records were preserved.')

    @app.cli.command('create-admin')
    @click.option('--email', prompt=True)
    @click.option('--name', default='Administrator', prompt=True)
    @click.password_option()
    def create_admin(email, name, password):
        """Create the first administrator; never uses a hardcoded password."""
        if db.session.scalar(select(User).where(User.role == 'Admin')):
            raise click.ClickException('An administrator already exists; use User Management.')
        if len(password) < 12 or len(password) > 256 or '@' not in email:
            raise click.ClickException('Use a valid email and a password of 12–256 characters.')
        app_document()
        db.session.add(User(id='demo-admin', email=email.strip().lower(), name=name,
                            password_hash=generate_password_hash(password), role='Admin', active=True))
        db.session.commit()
        click.echo('Administrator created.')

    from .erp_api import init_erp
    init_erp(app)
    return app


app = create_app()
