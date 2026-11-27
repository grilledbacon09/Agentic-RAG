from datetime import datetime, timezone, timedelta
from uuid import uuid4
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from psycopg2.extras import Json

from agents.models import ConversationSession, ConversationPhase, UserInput
from agents.persistence import session_to_dict
from agents.conversation_formatter import WELCOME_MESSAGE
from database.app_connection import transaction
from repositories import chats as repo
from repositories.users import profile
from services.auth import member_transaction, digest
from services.chat_worker import run_turn


def create(member, title):
    with member_transaction(member) as cursor:
        p = profile(cursor, member.user_id)
        age = p['age']
        stale_age = p['age_recorded_at'] and p['age_recorded_at'] < datetime.now(timezone.utc)-timedelta(days=365)
        session = ConversationSession(phase=ConversationPhase.COLLECTING, user_input=UserInput(
            symptoms=[], age=None if stale_age else age, allergies=p['allergies'],
            current_drug_ids=[m['drug_id'] for m in p['medications']],
            current_drug_names=[m['name'] for m in p['medications']]))
        if p['allergy_status'] != 'unknown':
            session.confirmed_slots.add('allergies')
        if p['medication_status'] != 'unknown':
            session.confirmed_slots.add('current_meds')
        state = session_to_dict(session)
        state.pop('turns')
        chat_id = str(uuid4())
        cursor.execute('''INSERT INTO app.chats(id,user_id,title,profile_version,profile_snapshot,session_state,next_sequence)
            VALUES (%s,%s,%s,%s,%s,%s,2)''',
            (chat_id, member.user_id, title, p['version'], Json(jsonable_encoder(p)), Json(state)))
        opening = WELCOME_MESSAGE
        if stale_age:
            opening += '\n\n저장된 나이가 오래되었습니다. 현재 나이를 다시 알려주세요.'
        repo.add_message(cursor, chat_id, 1, 'assistant', opening)
    return {'id': chat_id, 'title': title}


def send(member, chat_id, content, client_id, confirm_profile=False):
    with member_transaction(member) as cursor:
        chat = repo.owned_chat(cursor, member, chat_id)
        if chat['state_schema_version'] != 1:
            raise HTTPException(409, '지원되지 않는 상담 상태 버전입니다.')
        # Check idempotency first; replay must not be blocked by later profile edits.
        cursor.execute('SELECT id FROM app.chat_requests WHERE chat_id=%s AND client_request_id=%s', (chat_id, client_id))
        existing = cursor.fetchone()
        current = profile(cursor, member.user_id)
        state = dict(chat['session_state'])
        acknowledged = state.get('_acknowledged_profile_version', chat['profile_version'])
        if not existing and current['version'] != acknowledged and not confirm_profile:
            raise HTTPException(409, {'code': 'profile_changed', 'message': '건강설정이 변경되었습니다. 기존 상담 정보로 계속하거나 새 상담을 시작해주세요.'})
        claimed = repo.claim(cursor, chat, client_id, digest(content))
        if 'request_id' in claimed:
            cursor.execute('SELECT role,content FROM app.chat_messages WHERE chat_id=%s AND sequence>=%s ORDER BY sequence',
                (chat_id, state.get('_context_start_sequence', 1)))
            state['turns'] = [dict(r) for r in cursor.fetchall()]
            if confirm_profile:
                state['_acknowledged_profile_version'] = current['version']
    # Raise outside transaction so reclaimed leases stay failed.
    if 'error' in claimed:
        raise HTTPException(409, claimed['error'])
    if 'result' in claimed:
        return claimed['result']
    try:
        output = run_turn(state, content)
        output['metadata'] = repo.display_metadata(output['metadata'])
        repo.validate_output(output['content'], output['metadata'])
        saved_state = dict(output['state'])
        engine_turns = saved_state.pop('turns', [])
        if '_acknowledged_profile_version' in state:
            saved_state['_acknowledged_profile_version'] = state['_acknowledged_profile_version']
        with member_transaction(member) as cursor:
            latest = repo.owned_chat(cursor, member, chat_id)
            if latest['revision'] != chat['revision']:
                raise HTTPException(409, {'code': 'failed', 'message': '상담 상태가 변경되어 응답을 저장하지 않았습니다.'})
            cursor.execute('''UPDATE app.chat_requests SET status='completed',lease_token=NULL,lease_expires_at=NULL
                WHERE id=%s AND chat_id=%s AND status='processing' AND lease_token=%s AND lease_expires_at>now()
                RETURNING id''', (claimed['request_id'], chat_id, claimed['lease_token']))
            if not cursor.fetchone():
                raise HTTPException(409, {'code': 'failed', 'message': '처리 권한이 만료되어 응답을 저장하지 않았습니다.'})
            seq = latest['next_sequence']
            # A reset keeps the visible history but starts a fresh engine context.
            saved_state['_context_start_sequence'] = max(1, seq + 2 - len(engine_turns))
            user_id = repo.add_message(cursor, chat_id, seq, 'user', content, request_id=claimed['request_id'])
            message_id = repo.add_message(cursor, chat_id, seq+1, 'assistant', output['content'], output['metadata'], claimed['request_id'])
            cursor.execute('UPDATE app.chats SET session_state=%s,revision=revision+1,next_sequence=%s WHERE id=%s',
                (Json(saved_state), seq+2, chat_id))
        return {'role': 'ai', 'content': output['content'], 'debug_trace': None, **output['metadata'], 'message_id': message_id, 'user_message_id': user_id}
    except Exception:
        # A deleted request stays deleted; never INSERT or upsert on failure.
        try:
            with transaction() as cursor:
                cursor.execute('''UPDATE app.chat_requests SET status='failed',lease_token=NULL,lease_expires_at=NULL
                    WHERE id=%s AND chat_id=%s AND status='processing' AND lease_token=%s''',
                    (claimed['request_id'], chat_id, claimed['lease_token']))
        except HTTPException:
            pass  # Expiry reclamation handles database outages.
        raise
