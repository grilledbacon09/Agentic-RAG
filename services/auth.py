import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException, Request

from database.app_connection import transaction

COOKIE = 'member_session'
hasher = PasswordHasher()
_dummy_hash = hasher.hash(secrets.token_urlsafe(32))
_attempts = OrderedDict()
_rate_lock = threading.Lock()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_for(token):
    return hmac.new(token.encode(), b'member-csrf-v1', hashlib.sha256).hexdigest()


def origin_check(request):
    allowed = os.getenv('APP_ALLOWED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173').split(',')
    if request.headers.get('origin') not in [x.strip() for x in allowed]:
        raise HTTPException(403, '허용되지 않은 요청 출처입니다.')


def rate_limit(request, account, action):
    # Single initial worker, bounded memory. Never trust client X-Forwarded-For.
    now = time.monotonic()
    with _rate_lock:
        for kind, value, limit in [('ip', request.client.host if request.client else 'unknown', 30), ('account', account.strip().lower(), 10)]:
            key = (action, kind, digest(value))
            times = [t for t in _attempts.get(key, []) if t > now - 300]
            if len(times) >= limit:
                raise HTTPException(429, '요청이 너무 많습니다. 5분 후 다시 시도해주세요.')
            _attempts[key] = times + [now]
            _attempts.move_to_end(key)
        while len(_attempts) > 10000:
            _attempts.popitem(last=False)


def verify_password(encoded, password):
    try:
        return hasher.verify(encoded or _dummy_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True)
class Identity:
    user_id: str
    session_id: str
    token_hash: str
    email: str


def lock_identity(cursor, identity):
    # All member mutations lock user -> session -> chat -> request, in that order.
    cursor.execute('SELECT id FROM app.users WHERE id=%s AND status=\'active\' FOR UPDATE', (identity.user_id,))
    if not cursor.fetchone():
        raise HTTPException(401, '다시 로그인해주세요.')
    cursor.execute('''SELECT id FROM app.auth_sessions WHERE id=%s AND user_id=%s AND token_hash=%s
        AND revoked_at IS NULL AND expires_at>now() AND last_seen_at>now()-interval '30 minutes' FOR UPDATE''',
        (identity.session_id, identity.user_id, identity.token_hash))
    if not cursor.fetchone():
        raise HTTPException(401, '로그인이 만료되었습니다.')


@contextmanager
def member_transaction(identity):
    with transaction() as cursor:
        lock_identity(cursor, identity)
        yield cursor


def current_member(request: Request):
    token = request.cookies.get(COOKIE, '')
    if not token or len(token) > 256:
        raise HTTPException(401, '로그인이 필요합니다.')
    token_hash = digest(token)
    with transaction() as cursor:
        cursor.execute('''SELECT u.id AS user_id, u.email, s.id AS session_id FROM app.auth_sessions s
            JOIN app.users u ON u.id=s.user_id WHERE s.token_hash=%s''', (token_hash,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(401, '로그인이 필요합니다.')
        identity = Identity(str(row['user_id']), str(row['session_id']), token_hash, row['email'])
        lock_identity(cursor, identity)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin_check(request)
            supplied = request.headers.get('x-csrf-token', '')
            cursor.execute('SELECT csrf_token_hash FROM app.auth_sessions WHERE id=%s', (identity.session_id,))
            if not hmac.compare_digest(digest(supplied), cursor.fetchone()['csrf_token_hash']):
                raise HTTPException(403, '보안 토큰을 확인할 수 없습니다. 새로고침해주세요.')
        cursor.execute('UPDATE app.auth_sessions SET last_seen_at=now() WHERE id=%s', (identity.session_id,))
    return identity


def set_cookie(response, token):
    response.set_cookie(COOKIE, token, max_age=7*86400, httponly=True,
        secure=os.getenv('APP_COOKIE_SECURE', 'true').lower() == 'true', samesite='lax', path='/')


def clear_cookie(response):
    response.delete_cookie(COOKIE, path='/', httponly=True,
        secure=os.getenv('APP_COOKIE_SECURE', 'true').lower() == 'true', samesite='lax')
