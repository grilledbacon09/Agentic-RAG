from uuid import UUID
from datetime import datetime
import base64
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from services.auth import current_member, member_transaction
from services.chats import create
from repositories.chats import owned_chat, messages

router = APIRouter(prefix='/api/chats')


class NewChat(BaseModel):
    title: str = Field(default='새 상담', min_length=1, max_length=200)


@router.post('', status_code=201)
def create_chat(body: NewChat, member=Depends(current_member)):
    if not body.title.strip():
        raise HTTPException(422, '상담 제목을 입력해주세요.')
    return create(member, body.title.strip())


@router.get('')
def list_chats(cursor: str | None = Query(default=None, max_length=512), limit: int = Query(default=20, ge=1, le=100), member=Depends(current_member)):
    condition, params = '', [member.user_id]
    if cursor:
        try:
            time, chat_id = json.loads(base64.urlsafe_b64decode(cursor).decode())
            time, chat_id = datetime.fromisoformat(time), str(UUID(chat_id))
            if time.tzinfo is None:
                raise ValueError()
        except Exception:
            raise HTTPException(422, '잘못된 목록 커서입니다.') from None
        condition = 'AND (updated_at,id)<(%s,%s)'
        params += [time, chat_id]
    with member_transaction(member) as db:
        db.execute(f'SELECT id,title,updated_at FROM app.chats WHERE user_id=%s {condition} ORDER BY updated_at DESC,id DESC LIMIT %s', params+[limit+1])
        rows = [dict(r) for r in db.fetchall()]
    more, rows = len(rows)>limit, rows[:limit]
    next_cursor = base64.urlsafe_b64encode(json.dumps([rows[-1]['updated_at'].isoformat(), str(rows[-1]['id'])]).encode()).decode() if more else None
    return {'items': rows, 'next_cursor': next_cursor}


@router.get('/{chat_id}/messages')
def get_messages(chat_id: UUID, cursor: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=100), member=Depends(current_member)):
    with member_transaction(member) as db:
        owned_chat(db, member, str(chat_id))
        rows = messages(db, str(chat_id), cursor, limit+1)
    return {'items': rows[:limit], 'next_cursor': rows[limit-1]['sequence'] if len(rows)>limit else None}
