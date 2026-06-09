# api/diagnosis.py
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
import uuid

# 💡 AI 담당자가 새로 넘겨준 대화형 서비스 모듈 인터페이스 장착
from agents.chat_service import create_chat, send_message, ChatBundle
from agents.persistence import save_session_to_file, load_session_from_file

router = APIRouter(prefix="/api")

class ChatRequest(BaseModel):
    content: str
    chat_id: str # 💡 프론트엔드에서 관리하는 채팅방 ID 추가

# 💡 세션 관리 키를 "user_id:chat_id" 형태로 관리
SESSION_DB: Dict[str, ChatBundle] = {}

@router.post("/diagnosis")
async def predict_symptom(request: Request, response: Response, body: ChatRequest):
    user_msg = body.content
    chat_id = body.chat_id

    # 1. 💡 쿠키에서 유저 식별자(user_id) 추출
    user_id = request.cookies.get("user_id")

    if not user_id:
        user_id = str(uuid.uuid4())
        response.set_cookie(key="user_id", value=user_id, max_age=3600*24*30)

    # 세션 식별자 생성
    session_key = f"{user_id}_{chat_id}"

    try:
        # 2. 💡 해당 채팅방의 세션이 존재하는지 확인
        if session_key not in SESSION_DB:
            saved_session = load_session_from_file(session_key)

            if saved_session:
                bundle, _ = create_chat()
                bundle.session = saved_session
                SESSION_DB[session_key] = bundle
            else:
                bundle, opening_message = create_chat()
                SESSION_DB[session_key] = bundle

        current_bundle = SESSION_DB[session_key]
        updated_bundle, assistant_response, debug_trace = send_message(current_bundle, user_msg)

        SESSION_DB[session_key] = updated_bundle
        save_session_to_file(session_key, updated_bundle.session)
        # 6. 최종 응답 반환
        return {
            "role": "ai",
            "content": assistant_response,
            "debug_trace": debug_trace
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI Conversational Agent Error: {str(e)}")