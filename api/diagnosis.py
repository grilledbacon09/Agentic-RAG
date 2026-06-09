# api/diagnosis.py
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

# 💡 AI 담당자가 새로 넘겨준 대화형 서비스 모듈 인터페이스 장착
from chat_service import create_chat, send_message, ChatBundle

router = APIRouter(prefix="/api")

class ChatRequest(BaseModel):
    content: str

# 💡 클라우드 DB 연동 전까지 유저별 AI 대화 세션(ChatBundle)을 보관할 임시 메모리 저장소
# 구조: {"user_01": ChatBundle 객체}
SESSION_DB: Dict[str, ChatBundle] = {}

@router.post("/diagnosis")
async def predict_symptom(request: Request, body: ChatRequest):
    user_msg = body.content
    current_user = "user_01"  # 가상 유저 식별자
    
    try:
        # 1. 💡 해당 유저의 대화 세션(Bundle)이 메모리에 존재하는지 확인
        if current_user not in SESSION_DB:
            # 존재하지 않는다면 최초 1회 세션을 생성하고 환영 메시지를 획득합니다.
            # (config 객체는 main.py의 app.state 환경설정을 주입하거나 기본값 사용)
            bundle, opening_message = create_chat()
            SESSION_DB[current_user] = bundle
            
            # 최초 세션 생성 시점에는 바로 유저 메시지를 처리하기 위해 아래 흐름으로 이어집니다.
        
        # 2. 저장되어 있던 유저의 대화 세션을 꺼내옵니다.
        current_bundle = SESSION_DB[current_user]
        
        # 3. 💡 AI 담당자의 새 인터페이스인 send_message 함수를 가동합니다.
        # 매개변수: (현재 대화 번들, 유저가 친 대화 문자열)
        # 반환값: (갱신된 세션 번들, AI 최종 답변, 시스템 에이전트 추적 디버그 로그)
        updated_bundle, assistant_response, debug_trace = send_message(current_bundle, user_msg)
        
        # 4. 다음 문답을 위해 세션 갱신 상태를 다시 메모리 DB에 업데이트
        SESSION_DB[current_user] = updated_bundle
        
        # 5. 프론트엔드가 '최종 답변'과 '추론 트레이스 로그'를 분리하여 가독성 있게 표현할 수 있도록 전달
        return {
            "role": "ai",
            "content": assistant_response,
            "debug_trace": debug_trace  # 💡 에이전트 추론 로그 조각 추가!
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Conversational Agent Error: {str(e)}")