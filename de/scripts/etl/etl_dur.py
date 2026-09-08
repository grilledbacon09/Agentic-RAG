"""
[ETL 2] DUR API Bronze → Silver
실제 확인된 필드명 기준 (2026-08-30 샘플 검증)

병용금기 필드:
  성분A: INGR_KOR_NAME, INGR_ENG_NAME
  성분B: MIXTURE_INGR_KOR_NAME, MIXTURE_INGR_ENG_NAME
  제품A: ITEM_NAME, ITEM_SEQ, ENTP_NAME
  제품B: MIXTURE_ITEM_NAME, MIXTURE_ITEM_SEQ
  금기:  PROHBT_CONTENT, REMARK

노인주의/임부금기 등 단일 성분 유형:
  성분:  INGR_KOR_NAME, INGR_ENG_NAME
  제품:  ITEM_NAME, ITEM_SEQ, ENTP_NAME
"""
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils_s3 import list_keys, download_json, upload_json, silver_key

SOURCE_META = {
    "source_name": "식품의약품안전처 DUR(의약품 안전사용 서비스)",
    "source_url": "https://www.data.go.kr/data/15075057/openapi.do",
    "official_url": "https://www.dur.or.kr",
    "license": "공공누리 1유형",
    "provider": "식품의약품안전처",
}

# 유형별 필드 매핑 (실제 API 필드명 기준)
FIELD_MAP = {
    "combination_ban": {
        "desc": "병용금기",
        "ingr_a_fields": ["INGR_KOR_NAME", "INGR_ENG_NAME"],
        "ingr_b_fields": ["MIXTURE_INGR_KOR_NAME", "MIXTURE_INGR_ENG_NAME"],
        "item_b_fields": ["MIXTURE_ITEM_NAME", "MIXTURE_ITEM_SEQ"],
        "reason_fields": ["PROHBT_CONTENT", "REMARK"],
    },
    "pregnancy_ban": {
        "desc": "임부금기",
        "ingr_a_fields": ["INGR_KOR_NAME", "INGR_ENG_NAME"],
        "ingr_b_fields": [],
        "item_b_fields": [],
        "reason_fields": ["PROHBT_CONTENT", "REMARK"],
    },
    "dose_caution": {
        "desc": "용량주의",
        "ingr_a_fields": ["INGR_KOR_NAME", "INGR_ENG_NAME"],
        "ingr_b_fields": [],
        "item_b_fields": [],
        "reason_fields": ["REMARK"],
    },
    "elderly_caution": {
        "desc": "노인주의",
        "ingr_a_fields": ["INGR_KOR_NAME", "INGR_ENG_NAME"],
        "ingr_b_fields": [],
        "item_b_fields": [],
        "reason_fields": ["REMARK"],
    },
    "effect_duplicate": {
        "desc": "효능군중복",
        "ingr_a_fields": ["INGR_KOR_NAME", "INGR_ENG_NAME"],
        "ingr_b_fields": ["MIXTURE_INGR_KOR_NAME", "MIXTURE_INGR_ENG_NAME"],
        "item_b_fields": ["MIXTURE_ITEM_NAME", "MIXTURE_ITEM_SEQ"],
        "reason_fields": ["EFFECT_NAME", "REMARK"],
    },
    "age_specific_ban": {
        "desc": "특정연령대금기",
        "ingr_a_fields": ["INGR_KOR_NAME", "INGR_ENG_NAME"],
        "ingr_b_fields": [],
        "item_b_fields": [],
        "reason_fields": ["PROHBT_CONTENT", "REMARK"],
    },
    "dosing_period_caution": {
        "desc": "투여기간주의",
        "ingr_a_fields": ["INGR_KOR_NAME", "INGR_ENG_NAME"],
        "ingr_b_fields": [],
        "item_b_fields": [],
        "reason_fields": ["REMARK"],
    },
}


def clean_text(text) -> str:
    if not text:
        return ""
    return " ".join(str(text).split()).strip()


def get_field(item: dict, fields: list) -> str:
    for f in fields:
        val = item.get(f, "")
        if val:
            return clean_text(val)
    return ""


def build_text(item: dict, type_key: str) -> str:
    mapping = FIELD_MAP[type_key]
    desc = mapping["desc"]
    ingr_a = get_field(item, mapping["ingr_a_fields"])
    ingr_b = get_field(item, mapping["ingr_b_fields"])
    reason = get_field(item, mapping["reason_fields"])

    item_name = clean_text(item.get("ITEM_NAME", ""))
    mixture_name = clean_text(item.get("MIXTURE_ITEM_NAME", ""))

    # 텍스트 구성
    if ingr_b:
        text = f"[{desc}] 성분: {ingr_a} + {ingr_b}"
        if item_name and mixture_name:
            text += f" | 제품: {item_name} + {mixture_name}"
    else:
        text = f"[{desc}] 성분: {ingr_a}"
        if item_name:
            text += f" | 제품: {item_name}"

    if reason:
        text += f" | 사유: {reason}"

    return text


def make_dedup_key(item: dict, type_key: str) -> str:
    """중복 제거: 성분A + 성분B + 품목코드A + 품목코드B 조합"""
    mapping = FIELD_MAP[type_key]
    ingr_a = get_field(item, mapping["ingr_a_fields"])
    ingr_b = get_field(item, mapping["ingr_b_fields"])
    item_seq_a = clean_text(item.get("ITEM_SEQ", ""))
    item_seq_b = clean_text(item.get("MIXTURE_ITEM_SEQ", ""))
    return f"{ingr_a}|{ingr_b}|{item_seq_a}|{item_seq_b}"


def transform_dur_item(item: dict, type_key: str) -> dict | None:
    mapping = FIELD_MAP[type_key]
    ingr_a = get_field(item, mapping["ingr_a_fields"])
    if not ingr_a:
        return None

    ingr_b = get_field(item, mapping["ingr_b_fields"])
    reason = get_field(item, mapping["reason_fields"])
    text = build_text(item, type_key)

    item_seq = clean_text(item.get("ITEM_SEQ", ""))
    dur_seq = clean_text(item.get("DUR_SEQ", ""))
    doc_id = f"dur_{type_key}_{item_seq}_{dur_seq}"

    metadata = {
        "dur_type": type_key,
        "dur_desc": mapping["desc"],
        # 성분 정보
        "ingredient_a_kor": clean_text(item.get("INGR_KOR_NAME", "")),
        "ingredient_a_eng": clean_text(item.get("INGR_ENG_NAME", "")),
        "ingredient_b_kor": clean_text(item.get("MIXTURE_INGR_KOR_NAME", "")),
        "ingredient_b_eng": clean_text(item.get("MIXTURE_INGR_ENG_NAME", "")),
        # 제품A 정보
        "item_seq": item_seq,
        "item_name": clean_text(item.get("ITEM_NAME", "")),
        "manufacturer": clean_text(item.get("ENTP_NAME", "")),
        "class_name": clean_text(item.get("CLASS_NAME", "")),
        "etc_otc": clean_text(item.get("ETC_OTC_NAME", "")),
        "form_name": clean_text(item.get("FORM_NAME", "")),
        # 제품B 정보 (병용금기/효능군중복)
        "mixture_item_seq": clean_text(item.get("MIXTURE_ITEM_SEQ", "")),
        "mixture_item_name": clean_text(item.get("MIXTURE_ITEM_NAME", "")),
        "mixture_manufacturer": clean_text(item.get("MIXTURE_ENTP_NAME", "")),
        "mixture_class_name": clean_text(item.get("MIXTURE_CLASS_NAME", "")),
        "mixture_etc_otc": clean_text(item.get("MIXTURE_ETC_OTC_NAME", "")),
        # 금기 정보
        "reason": reason,
        "dur_seq": dur_seq,
        "notification_date": clean_text(item.get("NOTIFICATION_DATE", "")),
        # 출처
        **SOURCE_META,
        "etl_at": datetime.now().isoformat(),
    }

    return {
        "doc_id": doc_id,
        "doc_type": "dur_interaction",
        "text": text,
        "metadata": metadata,
    }


def main():
    logger.info("=" * 50)
    logger.info("[ETL 2] DUR 병용금기 정제 시작")
    logger.info("=" * 50)

    keys = [k for k in list_keys("bronze/api/dur/") if k.endswith(".json")]
    logger.info(f"Bronze 파일: {len(keys)}개")

    type_items = {t: [] for t in FIELD_MAP}
    seen = {t: set() for t in FIELD_MAP}
    total_raw = 0

    for i, key in enumerate(keys):
        try:
            data = download_json(key)
        except Exception as e:
            logger.warning(f"  스킵 [{key}]: {str(e)[:60]}")
            continue
        if not data:
            continue

        type_key = data.get("type", "")
        items = data.get("items", [])
        total_raw += len(items)

        if type_key not in FIELD_MAP:
            continue

        for item in items:
            dedup_key = make_dedup_key(item, type_key)
            if dedup_key in seen[type_key]:
                continue
            seen[type_key].add(dedup_key)

            transformed = transform_dur_item(item, type_key)
            if transformed:
                type_items[type_key].append(transformed)

        if (i + 1) % 1000 == 0:
            logger.info(f"  진행: {i+1}/{len(keys)}개 파일 처리")

    logger.info(f"원본: {total_raw}건")

    total_saved = 0
    for type_key, items in type_items.items():
        if not items:
            continue
        desc = FIELD_MAP[type_key]["desc"]
        logger.info(f"  [{desc}] {len(items)}건 저장 중...")

        batch_size = 500
        for i in range(0, len(items), batch_size):
            batch = items[i:i+batch_size]
            s_key = silver_key(
                f"dur_interactions/{type_key}",
                f"batch_{i//batch_size:04d}.json"
            )
            upload_json({
                "dur_type": type_key,
                "description": desc,
                "count": len(batch),
                "items": batch,
            }, s_key)
            total_saved += len(batch)

        logger.info(f"  [{desc}] ✅ {len(items)}건")

    logger.info(f"✅ DUR Silver 저장 완료: {total_saved}건")
    return total_saved


if __name__ == "__main__":
    main()