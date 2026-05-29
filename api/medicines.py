# api/medicines.py
from fastapi import APIRouter, Query, Request
from typing import Optional

router = APIRouter(prefix="/api")

# 💡 프론트엔드가 호출할 의약품 검색 API
@router.get("/medicines")
def get_medicines(
    request: Request, 
    search: Optional[str] = Query(None, description="검색어 (약품명 또는 성분명)")
):
    # 1. main.py 가동 시 서버 메모리(state)에 올려둔 진짜 drugs.json 데이터를 가져옵니다.
    # 이 데이터는 database/loader.py를 통해 이미 규격화되어 들어와 있습니다.
    all_drugs = request.app.state.DRUGS
    
    # 2. 검색어가 없으면 drugs.json의 전체 약물 리스트를 반환합니다.
    if not search:
        return all_drugs
    
    # 3. 검색어가 있으면 필터링을 진행합니다 (대소문자 구분 없음)
    search_keyword = search.lower()
    filtered_list = []
    
    for drug in all_drugs:
        # 한국어 약품명 추출
        name_ko = drug.name_ko.lower() if drug.name_ko else ""
        
        # 성분명 리스트를 하나의 문자열로 결합하여 검색에 대응
        ingredients = "".join(drug.ingredient).lower() if drug.ingredient else ""
        
        # 검색어가 약품명이나 성분명에 포함되어 있는지 검사
        if (search_keyword in name_ko) or (search_keyword in ingredients):
            filtered_list.append(drug)
            
    return filtered_list