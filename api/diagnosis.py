# api/diagnosis.py
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from agents.models import UserInput
from agents.enhanced_pipeline import run_enhanced_pipeline  # 💡 AI 담당자의 연동 핵심 함수!
from api.user import USER_DB  # user.py에 선언된 메모리 구조 참조

router = APIRouter(prefix="/api")

class ChatRequest(BaseModel):
    content: str

@router.post("/diagnosis")
async def predict_symptom(request: ChatRequest, req_obj: Request):
    user_msg = request.content
    current_user = "user_01"
    
    # 1. 유저의 세팅 데이터 실시간 조회
    user_info = USER_DB.get(current_user, {"gender": "", "age_group": "", "allergies": []})
    
    # 2. AI 담당자가 설계한 데이터 규격(UserInput) 객체로 포장
    user_input = UserInput(
        symptoms=[user_msg],
        current_drug_ids=[],
        current_drug_names=[],
        allergies=user_info.get("allergies", []),  # 💡 웹 프론트에서 넘어온 알레르기 연동
        conditions=[]
    )
    
    # 3. main.py 가동 시 서버 메모리에 들고 있는 마스터 데이터 스냅샷 획득
    drugs_db = req_obj.app.state.DRUGS
    symptoms_db = req_obj.app.state.SYMPTOMS
    
    try:
        # 4. 💡 가짜 조건문 대신 진짜 AI 멀티 에이전트 파이프라인 구동!
        ai_traced_response = run_enhanced_pipeline(user_input, drugs_db, symptoms_db, top_k=3)
        
        return {
            "role": "ai",
            "content": ai_traced_response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Agent Pipeline Error: {str(e)}")