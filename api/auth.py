import os
import re
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from database.app_connection import transaction
from services import auth

router = APIRouter(prefix='/api/auth')
POLICY_VERSION = 'demo-2026-11-27'
POLICIES = {
    'terms': '이 서비스는 졸업 프로젝트 시연용이며 상담은 참고 정보입니다. 계정은 본인만 사용하며 응급 상황에서는 의료기관에 연락하세요.',
    'privacy': '가입 이메일과 비밀번호 해시, 로그인 세션을 서비스 제공을 위해 저장합니다. 이메일 소유 인증과 이메일 기반 비밀번호 복구는 제공하지 않습니다. 탈퇴 시 계정과 연결 정보를 삭제합니다.',
    'health_data': '입력한 나이·성별·알레르기·복용약과 상담 내용을 저장하고 상담 처리에 사용합니다. 상담 처리를 위해 외부 AI 서비스로 입력 정보가 전달될 수 있습니다. 상담은 직접 삭제하거나 탈퇴할 때까지 보관하며 백업은 30일 보관합니다.',
}


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value.strip(' ')):
            raise ValueError('이메일 형식을 확인해주세요.')
        return value


class Signup(Credentials):
    password: str = Field(min_length=10, max_length=128)
    consents: dict[str, str]


@router.get('/policies')
def policies():
    return {'version': POLICY_VERSION, 'policies': POLICIES, 'demo': True}


@router.post('/signup', status_code=201)
def signup(body: Signup, request: Request):
    auth.origin_check(request)
    auth.rate_limit(request, body.email, 'signup')
    if body.consents != {key: POLICY_VERSION for key in POLICIES}:
        raise HTTPException(422, '현재 버전의 이용약관·개인정보·건강정보 처리 동의가 필요합니다.')
    user_id = str(uuid4())
    password_hash = auth.hasher.hash(body.password)
    with transaction() as cursor:
        cursor.execute('''INSERT INTO app.users(id,email,email_normalized,password_hash)
            VALUES (%s,%s,lower(btrim(%s)),%s)''', (user_id, body.email, body.email, password_hash))
        cursor.execute('INSERT INTO app.user_profiles(user_id) VALUES (%s)', (user_id,))
        for kind, version in body.consents.items():
            cursor.execute('''INSERT INTO app.user_consents(id,user_id,consent_type,policy_version,accepted_at)
                VALUES (%s,%s,%s,%s,now())''', (str(uuid4()), user_id, kind, version))
    return {'id': user_id, 'email': body.email}


@router.post('/login')
def login(body: Credentials, request: Request, response: Response):
    auth.origin_check(request)
    auth.rate_limit(request, body.email, 'login')
    with transaction() as cursor:
        cursor.execute('SELECT id,email,password_hash,status FROM app.users WHERE email_normalized=lower(btrim(%s))', (body.email,))
        user = cursor.fetchone()
    valid = auth.verify_password(user['password_hash'] if user else None, body.password)
    if not valid or not user or user['status'] != 'active':
        raise HTTPException(401, '이메일 또는 비밀번호가 올바르지 않습니다.')
    token = secrets.token_urlsafe(32)
    csrf = auth.csrf_for(token)
    with transaction() as cursor:
        cursor.execute('SELECT id FROM app.users WHERE id=%s AND status=\'active\' FOR UPDATE', (user['id'],))
        if not cursor.fetchone():
            raise HTTPException(401, '이메일 또는 비밀번호가 올바르지 않습니다.')
        previous = request.cookies.get(auth.COOKIE)
        if previous:
            cursor.execute('UPDATE app.auth_sessions SET revoked_at=now() WHERE token_hash=%s', (auth.digest(previous),))
        cursor.execute('''INSERT INTO app.auth_sessions(id,user_id,token_hash,csrf_token_hash,expires_at)
            VALUES (%s,%s,%s,%s,now()+interval '7 days')''',
            (str(uuid4()), str(user['id']), auth.digest(token), auth.digest(csrf)))
    auth.set_cookie(response, token)
    return {'id': str(user['id']), 'email': user['email'], 'csrf_token': csrf}


@router.get('/me')
def me(request: Request, member=Depends(auth.current_member)):
    return {'id': member.user_id, 'email': member.email, 'csrf_token': auth.csrf_for(request.cookies[auth.COOKIE])}


@router.post('/logout', status_code=204)
def logout(request: Request):
    auth.origin_check(request)
    try:
        member = auth.current_member(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    else:
        with auth.member_transaction(member) as cursor:
            cursor.execute('UPDATE app.auth_sessions SET revoked_at=now() WHERE id=%s', (member.session_id,))
    response = Response(status_code=204)
    auth.clear_cookie(response)
    response.delete_cookie('user_id', path='/')
    return response
