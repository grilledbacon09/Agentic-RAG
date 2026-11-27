from uuid import UUID
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from services.auth import current_member, member_transaction
from services.chats import send
from repositories.chats import owned_chat

router = APIRouter(prefix='/api')

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(min_length=1, max_length=8000)
    chat_id: UUID
    client_request_id: UUID
    confirm_profile: bool = False

    @field_validator('content')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('메시지를 입력해주세요.')
        return value

@router.post('/diagnosis')
def predict_symptom(body: ChatRequest, member=Depends(current_member)):
    return send(member, str(body.chat_id), body.content, str(body.client_request_id), body.confirm_profile)

@router.delete('/diagnosis/{chat_id}', status_code=204)
def delete_diagnosis(chat_id: UUID, member=Depends(current_member)):
    with member_transaction(member) as cursor:
        owned_chat(cursor, member, str(chat_id))
        cursor.execute('DELETE FROM app.chats WHERE id=%s AND user_id=%s', (str(chat_id), member.user_id))
    return Response(status_code=204)
