# api/diagnosis.py
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
import uuid
import json

# 💡 [Deep Debugging] agents 폴더 수정 없이 내부 로직 가로채기 (Monkeypatching)
import agents.conversation_agent
import agents.llm_orchestrator

# 1. GPT 원본 응답을 가로채기 위해 _parse_json 함수를 가로챕니다.
original_parse_json = agents.llm_orchestrator._parse_json

def patched_parse_json(text):
    print(f"\n--- [GPT RAW RESPONSE TEXT] ---")
    print(text if text else "(EMPTY TEXT)")
    print(f"--------------------------------\n")
    return original_parse_json(text)

# llm_orchestrator 모듈 내의 파싱 함수 교체
agents.llm_orchestrator._parse_json = patched_parse_json

# 2. 에이전트가 내부적으로 사용하는 orchestrate_turn_llm 함수를 가로챕니다.
original_orchestrate = agents.conversation_agent.orchestrate_turn_llm

def patched_orchestrate(*args, **kwargs):
    try:
        plan = original_orchestrate(*args, **kwargs)
        if plan:
            print(f"\n--- [RAW LLM OUTPUT DEBUG] ---")
            print(f" - Raw Reply: '{plan.reply}'")
            print(f" - Reasoning: {plan.reasoning}")
            print(f" -----------------------------\n")
        else:
            print("\n--- [RAW LLM OUTPUT DEBUG] Plan is NONE (Check API key or JSON format) ---\n")
        return plan
    except Exception as e:
        import traceback
        print(f"\n--- [RAW LLM OUTPUT DEBUG] EXCEPTION occurred ---")
        print(f"Error: {str(e)}")
        traceback.print_exc()
        return None

# 에이전트 내부의 함수 참조 교체
agents.conversation_agent.orchestrate_turn_llm = patched_orchestrate

# 나머지 모듈 임포트
from agents.chat_service import create_chat, send_message, ChatBundle
from agents.persistence import save_session_to_file, load_session_from_file

router = APIRouter(prefix="/api")

class ChatRequest(BaseModel):
    content: str
    chat_id: str

SESSION_DB: Dict[str, ChatBundle] = {}

@router.post("/diagnosis")
async def predict_symptom(request: Request, response: Response, body: ChatRequest):
    user_msg = body.content
    chat_id = body.chat_id

    user_id = request.cookies.get("user_id")

    from agents.llm_client import is_llm_enabled, get_api_key
    llm_active = is_llm_enabled()
    print(f"[Request] user_id: {user_id}, chat_id: {chat_id}, LLM_Enabled: {llm_active}")

    if not user_id:
        user_id = str(uuid.uuid4())
        response.set_cookie(
            key="user_id", 
            value=user_id, 
            max_age=3600*24*30,
            samesite="none",
            secure=True
        )
        print(f"[New User] Assigned ID: {user_id}")

    session_key = f"{user_id}_{chat_id}"

    try:
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
        print(f"[Context] Current Turn Count: {current_bundle.session.turn_count}")

        updated_bundle, assistant_response, debug_trace = send_message(current_bundle, user_msg)
        
        last_turn = updated_bundle.session.turns[-1] if updated_bundle.session.turns else None
        print(f"[Final API Response Debug]")
        print(f" - Phase: {updated_bundle.session.phase}")
        print(f" - Content: {assistant_response[:100]}...")

        SESSION_DB[session_key] = updated_bundle
        save_session_to_file(session_key, updated_bundle.session)
        
        return {
            "role": "ai",
            "content": assistant_response,
            "debug_trace": debug_trace,
            "user_id": user_id
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
