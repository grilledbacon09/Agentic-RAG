"""Opt-in tests against ONLY drug_app_test; isolated UUID accounts are cleaned up.

RUN_MEMBER_DB_TESTS=1 python -m pytest tests/test_members_integration.py
LLM/graph calls are replaced with deterministic responses here.
"""
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
pytestmark = pytest.mark.skipif(os.getenv('RUN_MEMBER_DB_TESTS') != '1', reason='explicit test DB opt-in required')


@pytest.fixture
def setup(monkeypatch):
    assert os.getenv('APP_DB_NAME') == 'drug_app_test', 'Never run these tests against production'
    monkeypatch.setenv('APP_COOKIE_SECURE', 'false')
    monkeypatch.setenv('APP_ALLOWED_ORIGINS', 'http://testserver')
    from main import app
    from services import auth
    from database.app_connection import transaction
    auth._attempts.clear()
    clients, ids = [], []
    def account():
        client = TestClient(app, headers={'Origin': 'http://testserver'})
        clients.append(client)
        email = f'test-{uuid4()}@example.invalid'
        password = 'Test-member-password-123'
        policies = client.get('/api/auth/policies').json()
        payload = dict(email=email, password=password, consents={key: policies['version'] for key in policies['policies']})
        response = client.post('/api/auth/signup', json=payload)
        assert response.status_code == 201, response.text
        ids.append(response.json()['id'])
        response = client.post('/api/auth/login', json=dict(email=email.upper(), password=password))
        assert response.status_code == 200, response.text
        client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        return client, payload, ids[-1]
    account.ids = ids
    yield account, transaction, monkeypatch
    with transaction() as cursor:
        for uid in ids:
            cursor.execute('DELETE FROM app.users WHERE id=%s', (uid,))
    for client in clients:
        client.close()


def fake_turn(state, content):
    state = deepcopy(state)
    state['has_recommendation'] = True
    state['turn_count'] += 1
    return {'state': state, 'content': '저장된 답변', 'metadata': {'data_sources': {'test': True}}}


def new_chat(client):
    response = client.post('/api/chats', json={'title': '통합 테스트'})
    assert response.status_code == 201, response.text
    return response.json()['id']


def send_body(chat_id, **kwargs):
    return dict(content='두통이 있어요', chat_id=chat_id, client_request_id=str(uuid4()), **kwargs)


def test_auth_csrf_profile_isolation_and_delete(setup):
    account, tx, mp = setup
    a, payload, uid = account()
    b, _, _ = account()
    assert a.get('/api/auth/me').status_code == 200
    duplicate = a.post('/api/auth/signup', json=payload | {'email': f" {payload['email'].upper()} "})
    assert duplicate.status_code == 409
    profile = a.get('/api/users/me/profile').json()
    body = {k: v for k, v in profile.items() if k != 'age_recorded_at'}
    body.update(age=35, allergy_status='known', allergies=['아스피린', '페니실린'])
    assert a.put('/api/users/me/profile', json=body, headers={'X-CSRF-Token': 'forged'}).status_code == 403
    assert a.put('/api/users/me/profile', json=body).status_code == 200
    assert a.put('/api/users/me/profile', json=body).status_code == 409
    assert b.get('/api/users/me/profile').json()['allergies'] == []
    chat = new_chat(a)
    assert b.get(f'/api/chats/{chat}/messages').status_code == 404
    assert b.post('/api/diagnosis', json=send_body(chat)).status_code == 404
    assert b.delete(f'/api/diagnosis/{chat}').status_code == 404
    response = a.request('DELETE', '/api/users/me', json={'password': payload['password']})
    assert response.status_code == 204, response.text
    assert a.get('/api/auth/me').status_code == 401
    with tx() as cursor:
        cursor.execute('SELECT user_id FROM app.deleted_users WHERE user_id=%s', (uid,))
        assert cursor.fetchone()
        for table, column in [('users','id'), ('user_profiles','user_id'), ('auth_sessions','user_id'), ('chats','user_id'), ('user_consents','user_id')]:
            cursor.execute(f'SELECT count(*) AS n FROM app.{table} WHERE {column}=%s', (uid,))
            assert cursor.fetchone()['n'] == 0


def test_chat_atomic_replay_reconnect_and_payload_conflict(setup):
    account, tx, mp = setup
    a, payload, uid = account()
    mp.setattr('services.chats.run_turn', fake_turn)
    chat = new_chat(a)
    body = send_body(chat)
    reply = a.post('/api/diagnosis', json=body)
    assert reply.status_code == 200, reply.text
    assert a.post('/api/diagnosis', json=body).json() == reply.json()
    assert a.post('/api/diagnosis', json=body | {'content': '다른 질문'}).status_code == 409
    with tx() as cursor:
        cursor.execute('SELECT revision,session_state FROM app.chats WHERE id=%s', (chat,))
        row = cursor.fetchone()
        assert row['revision'] == 1 and row['session_state']['has_recommendation']
        assert 'turns' not in row['session_state']
    assert len(a.get(f'/api/chats/{chat}/messages').json()['items']) == 3
    assert a.get('/api/chats').json()['items'][0]['id'] == chat
    from database.app_connection import close_pool
    close_pool()
    assert len(a.get(f'/api/chats/{chat}/messages').json()['items']) == 3
    from main import app
    with TestClient(app, headers={'Origin': 'http://testserver'}) as another:
        assert another.post('/api/auth/login', json={'email': payload['email'], 'password': payload['password']}).status_code == 200
        assert len(another.get(f'/api/chats/{chat}/messages').json()['items']) == 3
    assert a.delete(f'/api/diagnosis/{chat}').status_code == 204
    assert a.delete(f'/api/diagnosis/{chat}').status_code == 404


def test_expired_lease_and_late_worker_cannot_save(setup):
    account, tx, mp = setup
    a, _, _ = account()
    chat = new_chat(a)
    body = send_body(chat)
    def late(state, content):
        with tx() as cursor:
            cursor.execute("UPDATE app.chat_requests SET status='failed',lease_token=NULL,lease_expires_at=NULL WHERE chat_id=%s", (chat,))
        return fake_turn(state, content)
    mp.setattr('services.chats.run_turn', late)
    assert a.post('/api/diagnosis', json=body).status_code == 409
    assert len(a.get(f'/api/chats/{chat}/messages').json()['items']) == 1
    assert a.post('/api/diagnosis', json=body).json()['detail']['code'] == 'failed'
    mp.setattr('services.chats.run_turn', fake_turn)
    assert a.post('/api/diagnosis', json=send_body(chat)).status_code == 200


def test_logout_during_work_and_oversize_rollback(setup):
    account, tx, mp = setup
    a, payload, _ = account()
    chat = new_chat(a)
    def oversize(state, content):
        return {'state': state, 'content': '가'*8001, 'metadata': {}}
    mp.setattr('services.chats.run_turn', oversize)
    assert a.post('/api/diagnosis', json=send_body(chat)).status_code == 502
    assert len(a.get(f'/api/chats/{chat}/messages').json()['items']) == 1
    def logout(state, content):
        assert a.post('/api/auth/logout').status_code == 204
        return fake_turn(state, content)
    mp.setattr('services.chats.run_turn', logout)
    assert a.post('/api/diagnosis', json=send_body(chat)).status_code == 401
    with tx() as cursor:
        cursor.execute('SELECT count(*) AS n FROM app.chat_messages WHERE chat_id=%s', (chat,))
        assert cursor.fetchone()['n'] == 1


def test_idle_expiry_never_refreshes_and_origin(setup):
    account, tx, mp = setup
    a, _, uid = account()
    assert a.post('/api/chats', json={}, headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    with tx() as cursor:
        cursor.execute("UPDATE app.auth_sessions SET created_at=now()-interval '2 hours',last_seen_at=now()-interval '31 minutes' WHERE user_id=%s", (uid,))
    assert a.get('/api/auth/me').status_code == 401
    assert a.post('/api/auth/logout').status_code == 204


def test_profile_change_requires_confirmation_and_medications(setup):
    account, tx, mp = setup
    a, _, _ = account()
    chat = new_chat(a)
    mp.setattr('services.users.search_medications', lambda *args: [{'drug_id': '123456789', 'name': '처방약 스냅샷'}])
    body = dict(gender='unspecified', age=35, allergy_status='none', medication_status='known', allergies=[], medications=[{'drug_id':'123456789','name':'fake'}], version=1)
    result = a.put('/api/users/me/profile', json=body)
    assert result.status_code == 200, result.text
    assert result.json()['medications'][0]['name'] == '처방약 스냅샷'
    mp.setattr('services.chats.run_turn', fake_turn)
    request = send_body(chat)
    assert a.post('/api/diagnosis', json=request).json()['detail']['code'] == 'profile_changed'
    assert a.post('/api/diagnosis', json=request | {'confirm_profile': True}).status_code == 200
    assert a.post('/api/diagnosis', json=send_body(chat)).status_code == 200


def test_same_chat_concurrency_and_expired_lease_reclaim(setup):
    import threading
    account, tx, mp = setup
    a, _, _ = account()
    chat = new_chat(a)
    entered, release = threading.Event(), threading.Event()
    def slow(state, content):
        entered.set()
        assert release.wait(10)
        return fake_turn(state, content)
    mp.setattr('services.chats.run_turn', slow)
    body = send_body(chat)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(a.post, '/api/diagnosis', json=body)
        assert entered.wait(10)
        try:
            assert a.post('/api/diagnosis', json=body).json()['detail']['code'] == 'processing'
            assert a.post('/api/diagnosis', json=send_body(chat)).json()['detail']['code'] == 'busy'
            # A new request reclaims the expired lease before cron runs.
            with tx() as cursor:
                cursor.execute("UPDATE app.chat_requests SET lease_expires_at=now()-interval '1 second' WHERE chat_id=%s", (chat,))
            mp.setattr('services.chats.run_turn', fake_turn)
            assert a.post('/api/diagnosis', json=send_body(chat)).status_code == 200
        finally:
            release.set()
        assert first.result().status_code == 409
    assert len(a.get(f'/api/chats/{chat}/messages').json()['items']) == 3


def test_partial_save_failure_rolls_back_messages_and_state(setup):
    from fastapi import HTTPException
    from repositories import chats as repo
    account, tx, mp = setup
    a, _, _ = account()
    chat = new_chat(a)
    original = repo.add_message
    def broken(cursor, chat_id, seq, role, *args, **kwargs):
        if role == 'assistant':
            raise HTTPException(503, 'simulated storage failure')
        return original(cursor, chat_id, seq, role, *args, **kwargs)
    mp.setattr('services.chats.run_turn', fake_turn)
    mp.setattr(repo, 'add_message', broken)
    body = send_body(chat)
    assert a.post('/api/diagnosis', json=body).status_code == 503
    with tx() as cursor:
        cursor.execute('SELECT revision,next_sequence FROM app.chats WHERE id=%s', (chat,))
        assert dict(cursor.fetchone()) == {'revision': 0, 'next_sequence': 2}
        cursor.execute('SELECT status,finished_at FROM app.chat_requests WHERE chat_id=%s', (chat,))
        row = cursor.fetchone()
        assert row['status'] == 'failed' and row['finished_at'] is not None
    assert len(a.get(f'/api/chats/{chat}/messages').json()['items']) == 1


def test_signup_race_one_winner_and_login_rate_limit(setup):
    account, tx, mp = setup
    a, payload, _ = account()
    payload['email'] = f'race-{uuid4()}@example.invalid'
    with ThreadPoolExecutor(max_workers=2) as workers:
        replies = list(workers.map(lambda _: a.post('/api/auth/signup', json=payload), range(2)))
    for reply in replies:
        if reply.status_code == 201:
            account.ids.append(reply.json()['id'])
    assert sorted(reply.status_code for reply in replies) == [201, 409]
    responses = [a.post('/api/auth/login', json={'email': payload['email'], 'password': 'incorrect'}) for _ in range(11)]
    assert responses[0].status_code == 401
    assert responses[-1].status_code == 429


def test_delete_chat_and_account_during_engine_work(setup):
    account, tx, mp = setup
    a, payload, _ = account()
    chat = new_chat(a)
    def delete_chat(state, content):
        assert a.delete(f'/api/diagnosis/{chat}').status_code == 204
        return fake_turn(state, content)
    mp.setattr('services.chats.run_turn', delete_chat)
    assert a.post('/api/diagnosis', json=send_body(chat)).status_code == 404
    chat = new_chat(a)
    def delete_account(state, content):
        assert a.request('DELETE', '/api/users/me', json={'password': payload['password']}).status_code == 204
        return fake_turn(state, content)
    mp.setattr('services.chats.run_turn', delete_account)
    assert a.post('/api/diagnosis', json=send_body(chat)).status_code == 401
    with tx() as cursor:
        cursor.execute('SELECT count(*) AS n FROM app.chat_requests WHERE chat_id=%s', (chat,))
        assert cursor.fetchone()['n'] == 0
