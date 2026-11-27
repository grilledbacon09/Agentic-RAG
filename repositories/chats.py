import json
from uuid import uuid4
from fastapi import HTTPException
from psycopg2.extras import Json


def owned_chat(cursor, member, chat_id):
    cursor.execute('SELECT * FROM app.chats WHERE id=%s AND user_id=%s FOR UPDATE', (chat_id, member.user_id))
    chat = cursor.fetchone()
    if not chat:
        raise HTTPException(404, '상담을 찾을 수 없습니다.')
    return dict(chat)


def messages(cursor, chat_id, after=0, limit=100):
    cursor.execute('''SELECT id,role,content,metadata,sequence,request_id FROM app.chat_messages
        WHERE chat_id=%s AND sequence>%s ORDER BY sequence LIMIT %s''', (chat_id, after, limit))
    return [dict(row) for row in cursor.fetchall()]


def result_for(cursor, chat_id, request_id):
    cursor.execute('''SELECT id,role,content,metadata FROM app.chat_messages
        WHERE chat_id=%s AND request_id=%s ORDER BY sequence''', (chat_id, request_id))
    rows = cursor.fetchall()
    reply = next((row for row in rows if row['role'] == 'assistant'), None)
    user = next((row for row in rows if row['role'] == 'user'), None)
    if not reply or not user:
        raise HTTPException(503, '저장된 응답을 확인할 수 없습니다.')
    return {'role': 'ai', 'content': reply['content'], 'debug_trace': None, **reply['metadata'],
            'message_id': str(reply['id']), 'user_message_id': str(user['id'])}


def add_message(cursor, chat_id, sequence, role, content, metadata=None, request_id=None):
    mid = str(uuid4())
    cursor.execute('''INSERT INTO app.chat_messages(id,chat_id,request_id,sequence,role,content,metadata)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''', (mid, chat_id, request_id, sequence, role, content, Json(metadata or {})))
    return mid


def claim(cursor, chat, client_id, payload_hash):
    cursor.execute('''UPDATE app.chat_requests SET status='failed',lease_token=NULL,lease_expires_at=NULL
        WHERE chat_id=%s AND status='processing' AND lease_expires_at<=now()''', (str(chat['id']),))
    cursor.execute('SELECT * FROM app.chat_requests WHERE chat_id=%s AND client_request_id=%s FOR UPDATE', (str(chat['id']), client_id))
    prior = cursor.fetchone()
    if prior:
        if prior['payload_hash'] != payload_hash:
            return {'error': {'code': 'payload_conflict', 'message': '같은 요청 ID로 다른 내용을 보낼 수 없습니다.'}}
        if prior['status'] == 'completed':
            return {'result': result_for(cursor, str(chat['id']), str(prior['id']))}
        return {'error': {'code': prior['status'], 'message': '처리 중입니다. 잠시 후 재확인해주세요.' if prior['status'] == 'processing' else '실패한 요청입니다. 새 요청으로 다시 실행해주세요.'}}
    cursor.execute("SELECT id FROM app.chat_requests WHERE chat_id=%s AND status='processing'", (str(chat['id']),))
    if cursor.fetchone():
        return {'error': {'code': 'busy', 'message': '이 상담의 다른 요청이 처리 중입니다.'}}
    request_id, lease_token = str(uuid4()), str(uuid4())
    cursor.execute('''INSERT INTO app.chat_requests(id,chat_id,client_request_id,payload_hash,status,lease_token,lease_expires_at)
        VALUES (%s,%s,%s,%s,'processing',%s,now()+interval '120 seconds')''',
        (request_id, str(chat['id']), client_id, payload_hash, lease_token))
    return {'request_id': request_id, 'lease_token': lease_token}


def display_metadata(metadata):
    """Drop only optional trace fields as whole objects, never truncate JSON/text."""
    result = dict(metadata)
    for optional in ('debug_trace', 'reasoning_trace'):
        if len(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False)) <= 8000:
            break
        if optional in result:
            result.pop(optional)
            result['details_omitted'] = True
    return result


def validate_output(content, metadata):
    if not isinstance(content, str) or len(content) > 8000:
        raise HTTPException(502, {'code': 'failed', 'message': '생성 응답이 허용 길이를 초과하여 저장하지 못했습니다.'})
    if len(json.dumps(metadata, ensure_ascii=False, separators=(',', ':'), allow_nan=False)) > 8000:
        raise HTTPException(502, {'code': 'failed', 'message': '응답 부가정보가 허용 길이를 초과하여 저장하지 못했습니다.'})
