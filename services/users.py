import re
import os
from fastapi import HTTPException


def search_medications(query, limit=20):
    # Use the authoritative graph product catalogue, including prescription drugs.
    from agents.integrations.de_import import load_de_module
    try:
        module = load_de_module('graph_tools')
        if not os.getenv('NEO4J_URI') or not os.getenv('NEO4J_PASSWORD'):
            raise HTTPException(503, '복용약 검색 서버 설정이 필요합니다.')
        with module.DrugGraph() as graph:
            rows = graph.find_drug(query, limit=limit, otc_only=False)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, '복용약 검색 서버에 연결할 수 없습니다.') from None
    return [{'drug_id': str(row['item_seq']), 'name': row['name']}
            for row in rows if re.fullmatch(r'[0-9]{9}', str(row.get('item_seq', '')))]


def validate_medications(medications):
    result = []
    for med in medications:
        matches = search_medications(med.drug_id)
        match = next((row for row in matches if row['drug_id'] == med.drug_id), None)
        if not match or not match['name'] or len(match['name']) > 300:
            raise HTTPException(422, '검색 결과에서 유효한 복용약을 다시 선택해주세요.')
        result.append(match)
    return result
