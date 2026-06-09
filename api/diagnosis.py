# api/diagnosis.py
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
import uuid

# 💡 [Deep Debugging] agents 폴더 수정 없이 내부 로직 가로채기 (Monkeypatching)
import agents.conversation_agent
import agents.llm_orchestrator

# 에이전트가 내부적으로 사용하는 orchestrate_turn_llm 함수를 백업
original_orchestrate = agents.conversation_agent.orchestrate_turn_llm

def patched_orchestrate(*args, **kwargs):
    # 실제 LLM 호출 실행
    plan = original_orchestrate(*args, **kwargs)
    if plan:
        # 에이전트 코드가 덮어쓰기 전, LLM이 만든 순수 원본 데이터를 로그에 출력
        print(f"\n--- [RAW LLM OUTPUT DEBUG] ---")
        print(f" - Raw Reply: '{plan.reply}'")
        print(f" - Reasoning: {plan.reasoning}")
        print(f" - Slots Answered: {plan.slots_answered}")
        print(f" -----------------------------\n")
    else:
        print("\n--- [RAW LLM OUTPUT DEBUG] Plan is NONE ---\n")
    return plan

# 에이전트 내부의 함수 참조를 우리가 만든 디버깅용 함수로 교체
agents.conversation_agent.orchestrate_turn_llm = patched_orchestrate

# 이제 평소처럼 나머지 모달들 임포트
from agents.chat_service import create_chat, send_message, ChatBundle
from agents.persistence import save_session_to_file, load_session_from_file

router = APIRouter(prefix="/api")

class ChatRequest(BaseModel):
    content: str
    chat_id: str # 💡 프론트엔드에서 관리하는 채팅방 ID 추가

# 💡 세션 관리 키를 "user_id_chat_id" 형태로 관리
SESSION_DB: Dict[str, ChatBundle] = {}

@router.post("/diagnosis")
async def predict_symptom(request: Request, response: Response, body: ChatRequest):
    user_msg = body.content
    chat_id = body.chat_id

    # 1. 💡 쿠키에서 유저 식별자(user_id) 추출
    user_id = request.cookies.get("user_id")

    # [진단 로그] 서버에 들어온 쿠키 확인
    from agents.llm_client import is_llm_enabled, get_api_key
    llm_active = is_llm_enabled()
    print(f"[Request] user_id: {user_id}, chat_id: {chat_id}, LLM_Enabled: {llm_active}")

    if not user_id:
        user_id = str(uuid.uuid4())
        # 💡 운영 환경(HTTPS) 및 크로스 도메인을 위해 samesite="none", secure=True 필수
        response.set_cookie(
            key="user_id", 
            value=user_id, 
            max_age=3600*24*30,
            samesite="none",
            secure=True
        )
        print(f"[New User] Assigned ID: {user_id}")

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
                print(f"[Session] Restored from file: {session_key}")
            else:
                bundle, opening_message = create_chat()
                SESSION_DB[session_key] = bundle
                print(f"[Session] Created new: {session_key}")

        current_bundle = SESSION_DB[session_key]
        
        # [진단 로그] 대화 턴 수 확인
        print(f"[Context] Current Turn Count: {current_bundle.session.turn_count}")

        updated_bundle, assistant_response, debug_trace = send_message(current_bundle, user_msg)
        
        # 💡 [디버깅] AI가 이번 턴에 실제로 어떤 대화 객체를 생성했는지 상세 출력
        last_turn = updated_bundle.session.turns[-1] if updated_bundle.session.turns else None
        print(f"[Final API Response Debug]")
        print(f" - Phase: {updated_bundle.session.phase}")
        print(f" - Content: {assistant_response[:100]}...")

        SESSION_DB[session_key] = updated_bundle
        save_session_to_file(session_key, updated_bundle.session)
        
        # 6. 최종 응답 반환
        return {
            "role": "ai",
            "content": assistant_response,
            "debug_trace": debug_trace,
            "user_id": user_id # 프론트엔드 디버깅용
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI Conversational Agent Error: {str(e)}")
