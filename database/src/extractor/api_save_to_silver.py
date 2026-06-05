"""Bronze MinIO → Silver PostgreSQL 정제.

silver_drug_integration은 init_postresql.sql의 VIEW이므로
drug/taboo 테이블 적재 후 자동으로 조회 가능합니다.

실행 (DE 루트):
    python src/extractor/api_save_to_silver.py
"""

from __future__ import annotations

import json
import logging
import re

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import os
import set_client

logging.basicConfig(level=logging.INFO)

OTC_ONLY = os.getenv("SILVER_OTC_ONLY", "true").lower() in {"1", "true", "yes"}


def clean_text(text):
    """HTML 태그 제거 및 불필요한 공백 정리."""
    if not text:
        return ""
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_otc_item(item: dict) -> bool:
    for key in ("etcOtcName", "ETC_OTC_NAME", "etcOtcCode", "ETC_OTC_CODE"):
        value = str(item.get(key) or "").strip()
        if not value:
            continue
        if "일반" in value or value.upper() in {"02", "OTC"}:
            return True
        if "전문" in value or value.upper() in {"01", "ETC"}:
            return False
    return True


def process_bronze_to_silver(prefix: str) -> None:
    bucket = "bronze"
    conn = None
    try:
        response = set_client.s3.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/")
        if "Contents" not in response:
            print("처리할 새로운 데이터가 없습니다.")
            return

        conn = set_client.get_db_conn()
        cur = conn.cursor()

        for obj in response["Contents"]:
            file_key = obj["Key"]
            if not file_key.endswith(".json"):
                continue
            print(f"[*] Processing: {file_key}")

            file_obj = set_client.s3.get_object(Bucket=bucket, Key=file_key)
            raw_data = json.loads(file_obj["Body"].read().decode("utf-8"))
            items = raw_data.get("items", [])
            print(f"[*] {file_key} 파일에서 {len(items)}개의 아이템을 추출했습니다.")

            if prefix == "drug_info":
                process_drug_info(cur, items)
            elif prefix == "taboo_info":
                process_taboo_info(cur, items)

        conn.commit()
        print("[+] Silver Zone 적재 완료.")
    except Exception as e:
        print(f"[!] 에러 발생: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def process_drug_info(cur, raw_items):
    upsert_query = """
        INSERT INTO silver_drug_info (
            drug_id, name_ko, entp_name, class_name, ingredient,
            indications, dosage, warnings, interactions, side_effects, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (drug_id) DO UPDATE SET
            name_ko = EXCLUDED.name_ko,
            entp_name = EXCLUDED.entp_name,
            indications = EXCLUDED.indications,
            dosage = EXCLUDED.dosage,
            warnings = EXCLUDED.warnings,
            interactions = EXCLUDED.interactions,
            side_effects = EXCLUDED.side_effects,
            updated_at = NOW();
    """

    skipped = 0
    for item in raw_items:
        drug_id = str(item.get("itemSeq", item.get("ITEM_SEQ", ""))).strip()
        if not drug_id or drug_id == "None":
            continue
        if OTC_ONLY and not _is_otc_item(item):
            skipped += 1
            continue

        name = clean_text(item.get("itemName", item.get("ITEM_NAME")))
        company = clean_text(item.get("entpName"))
        efficacy = clean_text(item.get("efcyQesitm"))
        usage = clean_text(item.get("useMethodQesitm"))
        atpn_warn = item.get("atpnWarnQesitm") or ""
        atpn = item.get("atpnQesitm") or ""
        cautions = clean_text(f"{atpn_warn} {atpn}")
        interactions = clean_text(item.get("intrcQesitm"))
        side_effects = clean_text(item.get("seQesitm"))

        cur.execute(
            upsert_query,
            (
                drug_id,
                name,
                company,
                clean_text(item.get("className", item.get("CLASS_NAME"))),
                clean_text(item.get("mainItemIngr", item.get("MAIN_ITEM_INGR"))),
                efficacy,
                usage,
                cautions,
                interactions,
                side_effects,
            ),
        )
    if skipped:
        print(f"[*] 전문의약품 {skipped}건 스킵 (SILVER_OTC_ONLY={OTC_ONLY})", flush=True)


def process_taboo_info(cur, raw_items):
    upsert_query = """
        INSERT INTO silver_taboo_info (
            drug_id, drug_name, mixture_drug_id, mixture_drug_name,
            mixture_ingr_name, prohibited_content
        )
        VALUES (%s, %s, %s, %s, %s, %s);
    """

    for item in raw_items:
        drug_a_id = str(item.get("ITEM_SEQ", item.get("itemSeq", ""))).strip()
        drug_b_id = str(item.get("MIXTURE_ITEM_SEQ", item.get("mixtureItemSeq", ""))).strip()
        if not drug_a_id or not drug_b_id:
            continue

        main_ingr_raw = item.get("MAIN_INGR", item.get("mainIngr"))
        drug_a_ingr = main_ingr_raw.split("]")[-1].strip() if main_ingr_raw else ""
        drug_b_ingr = item.get("MIXTURE_INGR_KOR_NAME", item.get("mixtureIngrKorName"))
        prohbt_content = clean_text(item.get("PROHBT_CONTENT", item.get("prohbtContent")))

        cur.execute(
            upsert_query,
            (
                drug_a_id,
                item.get("ITEM_NAME", item.get("itemName")),
                drug_b_id,
                item.get("MIXTURE_ITEM_NAME", item.get("mixtureItemName")),
                drug_b_ingr,
                prohbt_content,
            ),
        )


if __name__ == "__main__":
    process_bronze_to_silver("drug_info")
    process_bronze_to_silver("taboo_info")
    print("[+] silver_drug_integration VIEW는 적재된 데이터를 자동 반영합니다.")
