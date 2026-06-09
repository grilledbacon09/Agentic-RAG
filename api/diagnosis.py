# api/diagnosis.py
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
import uuid
import json
import os

# 💡 [Deep Debugging] OpenAI 호출 과정에서 발생하는 모든 현상을 강제 출력
import agents.conversation_agent
import agents.llm_orchestrator
import agents.llm_client

def deep_debug_orchestrate(user_message, session, **kwargs):
    print(f"\n[Deep Debug] orchestrate_turn_llm 시작")
    
    # 1. 활성화 여부 확인
    enabled = agents.llm_orchestrator.is_llm_enabled()
    print(f" - LLM 활성화 상태: {enabled}")
    if not enabled:
        print(f" - API Key 존재 여부: {bool(agents.llm_orchestrator.get_api_key())}")
        print(f" - USE_LLM 설정 값: {os.getenv('USE_LLM')}")
        return None
        
    try:
        # 2. 클라이언트 생성 테스트
        print(f" - OpenAI 클라이언트 생성 시도...")
        client = agents.llm_orchestrator._client()
        
        # 3. 실제 API 호출 테스트 (짧은 메시지로 직접 시도)
        print(f" - OpenAI API 연결 테스트 (gpt-4o-mini 호출)...")
        test_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5
        )
        print(f" - API 연결 테스트 성공: '{test_resp.choices[0].message.content.strip()}'")
        
        # 4. 원본 함수 실행 및 결과 확인
        print(f" - 원본 에이전트 오케스트레이터 호출...")
        # 주의: 원본 함수 내부에 try-except가 있어 에러가 숨겨질 수 있으므로
        # 여기서는 원본 함수가 하는 일을 직접 수행하여 에러를 포착합니다.
        
        # 임시로 원본 호출
        plan = agents.llm_orchestrator.orchestrate_turn_llm(user_message, session, **kwargs)
        
        if plan is None:
            print(" - [경고] 원본 함수가 None을 반환했습니다. (파싱 실패 또는 내부 에러)")
        else:
            print(f" - 원본 함수 실행 성공! Reply: {plan.reply[:30]}...")
        
        return plan

    except Exception as e:
        print(f"\n!!! [Deep Debug] OpenAI 호출 중 에러 발생 !!!")
        print(f" - 에러 타입: {type(e).__name__}")
        print(f" - 에러 메시지: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

# 에이전트가 사용하는 함수를 우리 디버그 함수로 전역 교체
agents.conversation_agent.orchestrate_turn_llm = deep_debug_orchestrate

# JSON 파싱 로그도 유지
original_parse_json = agents.llm_orchestrator._parse_json
def patched_parse_json(text):
    print(f"\n--- [GPT RAW RESPONSE TEXT] ---")
    print(text if text else "(EMPTY TEXT)")
    print(f"--------------------------------\n")
    return original_parse_json(text)
agents.llm_orchestrator._parse_json = patched_parse_json

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

    print(f"\n[Request API] user_id: {user_id}, chat_id: {chat_id}")

    if not user_id:
        user_id = str(uuid.uuid4())
        response.set_cookie(
            key="user_id", value=user_id, max_age=3600*24*30,
            samesite="none", secure=True
        )

    session_key = f"{user_id}_{chat_id}"

    try:
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
        
        print(f"[Response API] Content: {assistant_response[:50]}...")

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
