# database/schemas.py
from pydantic import BaseModel

# 프론트엔드에서 백엔드로 보낼 때 (예: {"content": "머리가 너무 아파요"})
class ChatRequest(BaseModel):
    content: str

# 백엔드가 프론트엔드로 응답할 때 (예: {"role": "ai", "content": "[Multi-Agent...] ..."})
class ChatResponse(BaseModel):
    role: str
    content: str