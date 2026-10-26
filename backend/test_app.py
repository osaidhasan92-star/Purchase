"""Behavior tests: persistent storage, permissions, sessions, conflicts, import and files."""
import io
import os
import time
from copy import deepcopy

import pytest
from sqlalchemy import select
from werkzeug.security import generate_password_hash

from backend.app import Attachment, Audit, Document, LoginSession, User, create_app, db

PASSWORD = 'Testing-only-password-29'


@pytest.fixture
def app(tmp_path):
    test_url = os.environ.get('TEST_DATABASE_URL')
    if test_url and not test_url.split('?',1)[0].endswith('/purchase_test'):
        raise RuntimeError('TEST_DATABASE_URL must point to an isolated database named purchase_test')
    application = create_app({'TESTING': True, 'COOKIE_SECURE': False,
                              'SQLALCHEMY_DATABASE_URI': test_url or 'sqlite:///' + str(tmp_path / 'test.sqlite')})
    if test_url:
        with application.app_context():
            db.drop_all()
    runner = application.test_cli_runner()
    assert runner.invoke(args=['init-db']).exit_code == 0
    with application.app_context():
        for uid, role, manager in [('admin', 'Admin', None), ('viewer', 'Viewer', None),
                                   ('manager', 'Sales Manager', None), ('seller', 'Salesperson', 'manager'),
                                   ('hr', 'HR Manager', None)]:
            db.session.add(User(id=uid, name=uid, email=uid + '@example.test', role=role, manager_id=manager,
                                active=True, password_hash=generate_password_hash(PASSWORD)))
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


def session(app, who='admin'):
    client = app.test_client()
    response = client.post('/api/auth/login', json={'email': who + '@example.test', 'password': PASSWORD})
    assert response.status_code == 200, response.json
    return client, {'X-CSRF-Token': response.json['csrfToken']}


def patch(client, headers, changes, path='/api/state', revision=None):
    if revision is None:
        revision = client.get(path).json['revision']
    return client.patch(path, headers=headers, json={'revision': revision, 'changes': changes})


def test_authentication_and_no_credentials_in_responses(app):
    client = app.test_client()
    assert client.get('/api/state').status_code == 401
    assert client.post('/api/auth/login', json={'email': 'admin@example.test', 'password': 'bad'}).status_code == 401
    client, headers = session(app)
    state = client.get('/api/state').json
    assert 'password' not in str(state).lower()
    cookie = client.get_cookie('purchase_session')
    assert cookie.http_only and cookie.same_site == 'Lax'
    with app.app_context():
        user = db.session.get(User, 'admin')
        assert user.password_hash != PASSWORD
        stored = db.session.scalar(select(LoginSession))
        assert stored.token_hash != cookie.value


def test_csrf_origin_and_no_public_backend_files(app):
    client, headers = session(app)
    assert client.patch('/api/state', json={'revision': 1, 'changes': {}}).status_code == 403
    assert client.patch('/api/state', headers={**headers, 'Origin': 'https://evil.test'}, json={'revision': 1, 'changes': {}}).status_code == 403
    for path in ['/backend/app.py', '/instance/purchase.sqlite', '/.env', '/app.js.bak']:
        assert client.get(path).status_code == 404
    assert client.get('/bootstrap.html').status_code == 410
    assert client.get('/seed.html').status_code == 410


def test_persistence_across_app_instances_and_conflict(app):
    client, headers = session(app)
    revision = client.get('/api/state').json['revision']
    assert patch(client, headers, {'vendors': [{'id': 1, 'name': 'Saved supplier'}]}, revision=revision).status_code == 200
    assert patch(client, headers, {'vendors': []}, revision=revision).status_code == 409
    other = create_app({'TESTING': True, 'COOKIE_SECURE': False,
                        'SQLALCHEMY_DATABASE_URI': app.config['SQLALCHEMY_DATABASE_URI']})
    reader, _ = session(other)
    assert reader.get('/api/state').json['state']['vendors'][0]['name'] == 'Saved supplier'


def test_viewer_and_hr_privacy(app):
    admin, ah = session(app)
    assert patch(admin, ah, {'employees': [{'id': 1, 'name': 'Private payroll employee', 'salary': 100}]}, '/api/hr/state').status_code == 200
    viewer, vh = session(app, 'viewer')
    assert viewer.get('/api/hr/state').json['state']['employees'] == []
    assert patch(viewer, vh, {'vendors': [{'id': 4, 'name': 'Injected'}]}).status_code == 403
    assert patch(viewer, vh, {'payroll': [{'id': 1, 'status': 'Paid'}]}, '/api/hr/state').status_code == 403
    assert viewer.post('/api/users', headers=vh, json={}).status_code == 403
    assert viewer.get('/api/admin/export').status_code == 403
    hr, hh = session(app, 'hr')
    assert hr.get('/api/hr/state').json['state']['employees'][0]['salary'] == 100
    assert patch(hr, hh, {'attendance': [{'id': 'a', 'employee': '1 - Private payroll employee', 'date': '2026-10-26'}]}, '/api/hr/state').status_code == 200


def test_server_permissions_cannot_be_escalated(app):
    client, headers = session(app, 'viewer')
    roles = client.get('/api/state').json['state']['roles']
    roles['Viewer']['permissions']['vendors']['create'] = True
    assert patch(client, headers, {'roles': roles}).status_code == 403


def test_sales_scope_preserves_hidden_records(app):
    admin, ah = session(app)
    leads = [{'id': 1, 'customerId': 1, 'ownerId': 'seller', 'managerId': 'manager'},
             {'id': 2, 'customerId': 2, 'ownerId': 'someone-else', 'managerId': 'another-manager'}]
    assert patch(admin, ah, {'leads': leads, 'customers': [{'id': 1, 'name': 'My account'}, {'id': 2, 'name': 'Other team'}]}).status_code == 200
    seller, sh = session(app, 'seller')
    data = seller.get('/api/state').json['state']
    assert [r['id'] for r in data['leads']] == [1]
    assert [r['id'] for r in data['customers']] == [1]
    data['leads'][0]['contact'] = 'Updated'
    assert patch(seller, sh, {'leads': data['leads']}).status_code == 200
    all_leads = admin.get('/api/state').json['state']['leads']
    assert len(all_leads) == 2
    assert patch(seller, sh, {'leads': leads}).status_code == 403


def test_password_change_revokes_every_session(app):
    client, headers = session(app)
    other, _ = session(app)
    new = 'A-new-password-long-enough'
    response = client.post('/api/auth/change-password', headers=headers,
                           json={'currentPassword': PASSWORD, 'newPassword': new, 'confirmPassword': new})
    assert response.status_code == 200
    assert other.get('/api/auth/me').status_code == 401
    assert client.get('/api/auth/me').status_code == 401


def test_user_creation_hashing_and_revocation(app):
    admin, headers = session(app)
    profile = {'name': 'New user', 'email': 'new@example.test', 'role': 'Viewer', 'active': True, 'password': PASSWORD}
    response = admin.post('/api/users', headers=headers, json=profile)
    assert response.status_code == 200
    uid = response.json['id']
    assert 'password' not in response.json
    with app.app_context():
        assert db.session.get(User, uid).password_hash != PASSWORD
    client = app.test_client()
    assert client.post('/api/auth/login', json={'email': profile['email'], 'password': PASSWORD}).status_code == 200
    profile.update(active=False, password='')
    assert admin.put('/api/users/' + uid, headers=headers, json=profile).status_code == 200
    assert client.get('/api/auth/me').status_code == 401


def test_expired_session_and_logout(app):
    client, headers = session(app)
    assert client.post('/api/auth/logout', headers=headers, json={}).status_code == 200
    assert client.get('/api/auth/me').status_code == 401
    client, headers = session(app)
    with app.app_context():
        db.session.query(LoginSession).update({'expires': time.time() - 1})
        db.session.commit()
    assert client.get('/api/state').status_code == 401


def test_import_is_one_time_and_ignores_browser_accounts(app):
    admin, headers = session(app)
    data = {'app': {'vendors': [{'id': 44, 'name': 'Migrated'}],
                    'users': [{'id': 'old', 'name': 'Old account', 'email': 'old@example.test', 'role': 'Viewer', 'password': 'plaintext'}]},
            'hr': {'employees': [{'id': 'e', 'name': 'Employee', 'salary': 10}]}}
    assert admin.post('/api/admin/import', headers=headers, json=data).status_code == 200
    with app.app_context():
        user = db.session.get(User, 'old')
        assert not user.active and user.password_hash != 'plaintext'
    assert admin.post('/api/admin/import', headers=headers, json=data).status_code == 409
    assert admin.get('/api/admin/export').json['hr']['employees'][0]['name'] == 'Employee'


def test_invalid_business_payload_is_rejected(app):
    client, headers = session(app)
    assert patch(client, headers, {'invoices': [{'id': 1, 'amount': -1}]}).status_code == 400
    assert patch(client, headers, {'vendors': [{'id': 1}, {'id': 1}]}).status_code == 400
    assert patch(client, headers, {'vendors': [{'id': 1, 'password': 'plaintext'}]}).status_code == 400
    assert patch(client, headers, {'unknown': []}).status_code == 400
    assert client.patch('/api/state', headers=headers, json={'changes': {}}).status_code == 428


def test_pdf_attachment_storage_and_access(app):
    admin, headers = session(app)
    response = admin.post('/api/attachments', headers=headers,
                          data={'module': 'quotations', 'file': (io.BytesIO(b'%PDF-1.7\ntest'), 'offer.pdf')})
    assert response.status_code == 200
    aid = response.json['attachmentPath']
    assert admin.get('/api/attachments/' + aid).data.startswith(b'%PDF-')
    assert app.test_client().get('/api/attachments/' + aid).status_code == 401
    viewer, vh = session(app, 'viewer')
    assert viewer.post('/api/attachments', headers=vh,
                       data={'module': 'quotations', 'file': (io.BytesIO(b'%PDF-1.7'), 'x.pdf')}).status_code == 403
    assert admin.post('/api/attachments', headers=headers,
                      data={'module': 'quotations', 'file': (io.BytesIO(b'<script>bad</script>'), 'fake.pdf')}).status_code == 400


def test_login_rate_limit(app):
    client = app.test_client()
    for _ in range(10):
        assert client.post('/api/auth/login', json={'email': 'missing@example.test', 'password': 'bad'}).status_code == 401
    assert client.post('/api/auth/login', json={'email': 'missing@example.test', 'password': 'bad'}).status_code == 429
