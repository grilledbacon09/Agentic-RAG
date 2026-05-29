# api/user.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Any

router = APIRouter(prefix="/api/user")

class UserSetting(BaseModel):
    user_id: str
    gender: str
    age_group: str
    allergies: List[str]

# 💡 다른 파일(diagnosis.py)에서도 조회할 수 있도록 전역 변수 유지
USER_DB: Dict[str, Dict[str, Any]] = {}

@router.post("/setting")
def save_user_setting(setting: UserSetting):
    USER_DB[setting.user_id] = {
        "gender": setting.gender,
        "age_group": setting.age_group,
        "allergies": setting.allergies
    }
    return {"status": "success", "message": "유저 설정이 서버에 안전하게 저장되었습니다."}

@router.get("/setting/{user_id}")
def get_user_setting(user_id: str):
    if user_id not in USER_DB:
        return {"user_id": user_id, "gender": "", "age_group": "", "allergies": []}
    return {"user_id": user_id, **USER_DB[user_id]}