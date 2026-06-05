"""개발/테스트용 Silver 데이터 시드.

MSD 크롤링이나 공공 API 없이도 파이프라인을 검증할 수 있도록
프로젝트 루트 data/*.json을 PostgreSQL Silver 테이블에 적재합니다.

실행 (DE 루트):
    python src/extractor/seed_dev_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import set_client
from paths import AI_DRUGS_JSON, AI_SYMPTOMS_JSON

# 증상 검색 품질을 위해 기본 설명 텍스트를 보강합니다.
SYMPTOM_ENRICHMENT: dict[str, dict] = {
    "두통": {
        "category": "신경과",
        "is_red_flag": False,
        "cause": (
            "두통은 긴장성 두통, 편두통, 부비동염, 고혈압, 탈수, "
            "수면 부족, 스트레스 등 다양한 원인으로 발생할 수 있습니다."
        ),
        "warning_sign": (
            "갑작스러운 심한 두통, 의식 저하, 시야 이상, 발열, "
            "목 경직, 사지 마비가 동반되면 응급 상황일 수 있습니다."
        ),
        "meet_doc": (
            "갑작스럽고 심한 두통, 신경학적 증상 동반, 50세 이후 새로 생긴 "
            "두통, 외상 후 두통, 점점 심해지는 두통은 즉시 병원을 방문하세요."
        ),
        "action_guide": (
            "충분한 수분 섭취, 휴식, 소음·빛 자극 최소화. "
            "일반적인 긴장성 두통에는 해열진통제(아세트아미노펜 등)가 도움이 될 수 있습니다."
        ),
        "pre_exist_condition": (
            "편두통, 고혈압, 부비동염, 안구 질환, 경추 질환 등이 "
            "두통의 기저 원인이 될 수 있습니다."
        ),
    },
    "발열": {
        "category": "전신",
        "cause": "감염, 염증, 면역 반응 등으로 체온 조절 중추가 상승할 때 발생합니다.",
        "warning_sign": "39도 이상 고열, 의식 변화, 호흡 곤란, 경련이 동반되면 주의가 필요합니다.",
        "meet_doc": "고열이 3일 이상 지속되거나 심한 전신 쇠약이 동반되면 진료가 필요합니다.",
        "action_guide": "수분 섭취, 해열제 복용, 충분한 휴식을 권장합니다.",
    },
    "통증": {
        "category": "전신",
        "cause": "염증, 근육 긴장, 신경 자극, 외상 등으로 발생합니다.",
        "action_guide": "원인에 따라 해열진통제, 휴식, 국소 치료가 도움이 될 수 있습니다.",
    },
}


def _load_json(path: Path) -> list:
    if not path.exists():
        print(f"[!] 파일 없음: {path}")
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def seed_symptoms() -> int:
    rows = _load_json(AI_SYMPTOMS_JSON)
    upsert = """
        INSERT INTO silver_symptom (
            symptom_id, name, category, is_red_flag,
            cause, warning_sign, meet_doc, action_guide,
            pre_exist_condition, updated_at
        ) VALUES (
            %(symptom_id)s, %(name)s, %(category)s, %(is_red_flag)s,
            %(cause)s, %(warning_sign)s, %(meet_doc)s, %(action_guide)s,
            %(pre_exist_condition)s, NOW()
        )
        ON CONFLICT (symptom_id) DO UPDATE SET
            name = EXCLUDED.name,
            category = EXCLUDED.category,
            is_red_flag = EXCLUDED.is_red_flag,
            cause = EXCLUDED.cause,
            warning_sign = EXCLUDED.warning_sign,
            meet_doc = EXCLUDED.meet_doc,
            action_guide = EXCLUDED.action_guide,
            pre_exist_condition = EXCLUDED.pre_exist_condition,
            updated_at = NOW();
    """
    payload = []
    for row in rows:
        name = row["name"]
        extra = SYMPTOM_ENRICHMENT.get(name, {})
        payload.append({
            "symptom_id": row["symptom_id"],
            "name": name,
            "category": extra.get("category"),
            "is_red_flag": extra.get("is_red_flag", False),
            "cause": extra.get("cause"),
            "warning_sign": extra.get("warning_sign"),
            "meet_doc": extra.get("meet_doc"),
            "action_guide": extra.get("action_guide") or row.get("action_guide"),
            "pre_exist_condition": extra.get("pre_exist_condition"),
        })

    conn = set_client.get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(upsert, payload)
        conn.commit()
    finally:
        conn.close()
    print(f"[+] silver_symptom 시드 완료: {len(payload)}건")
    return len(payload)


def seed_drugs() -> int:
    rows = _load_json(AI_DRUGS_JSON)
    upsert = """
        INSERT INTO silver_drug_info (
            drug_id, name_ko, class_name, ingredient,
            indications, dosage, warnings, side_effects, updated_at
        ) VALUES (
            %(drug_id)s, %(name_ko)s, %(class_name)s, %(ingredient)s,
            %(indications)s, %(dosage)s, %(warnings)s, %(side_effects)s, NOW()
        )
        ON CONFLICT (drug_id) DO UPDATE SET
            name_ko = EXCLUDED.name_ko,
            class_name = EXCLUDED.class_name,
            ingredient = EXCLUDED.ingredient,
            indications = EXCLUDED.indications,
            dosage = EXCLUDED.dosage,
            warnings = EXCLUDED.warnings,
            side_effects = EXCLUDED.side_effects,
            updated_at = NOW();
    """
    payload = []
    for row in rows:
        ingredient = row.get("ingredient")
        if isinstance(ingredient, list):
            ingredient = ", ".join(ingredient)
        payload.append({
            "drug_id": row["drug_id"],
            "name_ko": row["name_ko"],
            "class_name": row.get("category"),
            "ingredient": ingredient,
            "indications": row.get("indications"),
            "dosage": row.get("dosage"),
            "warnings": row.get("warnings"),
            "side_effects": None,
        })

    conn = set_client.get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(upsert, payload)
        conn.commit()
    finally:
        conn.close()
    print(f"[+] silver_drug_info 시드 완료: {len(payload)}건")
    return len(payload)


def seed_taboo() -> int:
    rows = _load_json(AI_DRUGS_JSON)
    insert_sql = """
        INSERT INTO silver_taboo_info (
            drug_id, drug_name, mixture_drug_id, prohibited_content
        ) VALUES (%s, %s, %s, %s);
    """
    drug_names = {r["drug_id"]: r["name_ko"] for r in rows}
    records = []
    for row in rows:
        for other_id in row.get("combination_contraindication") or []:
            records.append((
                row["drug_id"],
                row["name_ko"],
                other_id,
                f"{row['name_ko']}과(와) {drug_names.get(other_id, other_id)} 병용 금기",
            ))

    if not records:
        print("[*] silver_taboo_info 시드 대상 없음")
        return 0

    conn = set_client.get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM silver_taboo_info;")
            cur.executemany(insert_sql, records)
        conn.commit()
    finally:
        conn.close()
    print(f"[+] silver_taboo_info 시드 완료: {len(records)}건")
    return len(records)


if __name__ == "__main__":
    print(f"[*] 시드 소스: {AI_SYMPTOMS_JSON.name}, {AI_DRUGS_JSON.name}")
    seed_symptoms()
    seed_drugs()
    seed_taboo()
    print("[+] silver_drug_integration 뷰는 drug/taboo 데이터 반영 후 자동 갱신됩니다.")
