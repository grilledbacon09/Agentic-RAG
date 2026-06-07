"""팀원 data.zip 추출본 → PostgreSQL Silver 적재.

data.zip을 DE/data/ 아래에 풀었다고 가정합니다.
  DE/data/msd_source/silver_data.csv
  DE/data/minio/bronze/drug_info/.../part.1

실행 (DE 루트):
    python src/extractor/import_team_data.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import pandas as pd
import set_client
from minio_part import extract_items_from_part, find_latest_part, iter_taboo_items_from_part
from paths import DATA_DIR, MSD_SOURCE_DIR, TEAM_TABOO_INFO_ROOT

PROCESSED_DIR = DATA_DIR / "processed"
SILVER_CSV = MSD_SOURCE_DIR / "silver_data.csv"
DRUG_INFO_ROOT = DATA_DIR / "minio" / "bronze" / "drug_info"
SYMPTOM_JSON_ROOT = DATA_DIR / "minio" / "silver" / "symptoms"

OTC_ONLY = os.getenv("SILVER_OTC_ONLY", "false").lower() in {"1", "true", "yes"}
SKIP_TABOO = os.getenv("SKIP_TABOO", "false").lower() in {"1", "true", "yes"}
TABOO_BATCH_SIZE = int(os.getenv("TABOO_BATCH_SIZE", "5000"))


def _clean_text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).replace("\x00", "")
    text = re.sub(r"<[^>]*>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


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


def _require_paths() -> tuple[Path, Path]:
    missing: list[str] = []
    if not SILVER_CSV.exists():
        missing.append(str(SILVER_CSV))
    drug_part = find_latest_part(DRUG_INFO_ROOT)
    if drug_part is None:
        missing.append(str(DRUG_INFO_ROOT / "**/part.1"))
    if missing:
        raise FileNotFoundError(
            "팀 데이터 파일이 없습니다. data.zip을 DE/data/ 에 압축 해제하세요.\n"
            + "\n".join(f"  - {p}" for p in missing)
        )
    return SILVER_CSV, drug_part  # type: ignore[return-value]


def _save_clean_json(name: str, items: list[dict]) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / name
    with out.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"[+] 정제 JSON 저장: {out} ({len(items)}건)", flush=True)
    return out


def import_symptoms_from_csv(csv_path: Path) -> int:
    df = pd.read_csv(csv_path)
    print(f"[+] 증상 CSV 로드: {len(df)}행 ({csv_path.name})", flush=True)

    upsert = """
        INSERT INTO silver_symptom (
            symptom_id, name, category, is_red_flag,
            cause, warning_sign, meet_doc, action_guide, pre_exist_condition, updated_at
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

    payload: list[dict] = []
    for _, row in df.iterrows():
        symptom_id = _clean_text(row.get("symptom_id"))
        name = _clean_text(row.get("name"))
        if not symptom_id or not name:
            continue
        context = _clean_text(row.get("context"))
        payload.append({
            "symptom_id": symptom_id,
            "name": name,
            "category": _clean_text(row.get("category")) or None,
            "is_red_flag": _parse_bool(row.get("is_red_flag")),
            "cause": _clean_text(row.get("cause")) or None,
            "warning_sign": _clean_text(row.get("warning_sign")) or None,
            "meet_doc": context or None,
            "action_guide": _clean_text(row.get("action_guide")) or None,
            "pre_exist_condition": _clean_text(row.get("pre_exist_condition")) or None,
        })

    conn = set_client.get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(upsert, payload)
        conn.commit()
    finally:
        conn.close()

    print(f"[+] silver_symptom 적재: {len(payload)}건", flush=True)
    return len(payload)


def import_symptoms_from_minio_json() -> int:
    """CSV가 없을 때 MinIO silver/symptoms part.1 fallback."""
    part = find_latest_part(SYMPTOM_JSON_ROOT)
    if part is None:
        return 0
    items = extract_items_from_part(part)
    if not items:
        return 0
    df = pd.DataFrame(items)
    temp_csv = PROCESSED_DIR / "symptoms_from_minio.csv"
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(temp_csv, index=False)
    return import_symptoms_from_csv(temp_csv)


def import_drugs_from_part(part_path: Path) -> int:
    items = extract_items_from_part(part_path)
    print(f"[+] drug_info part 추출: {len(items)}건 ({part_path})", flush=True)
    _save_clean_json("drug_info_clean.json", items)

    upsert = """
        INSERT INTO silver_drug_info (
            drug_id, name_ko, entp_name, class_name, ingredient,
            indications, dosage, warnings, interactions, side_effects, updated_at
        ) VALUES (
            %(drug_id)s, %(name_ko)s, %(entp_name)s, %(class_name)s, %(ingredient)s,
            %(indications)s, %(dosage)s, %(warnings)s, %(interactions)s,
            %(side_effects)s, NOW()
        )
        ON CONFLICT (drug_id) DO UPDATE SET
            name_ko = EXCLUDED.name_ko,
            entp_name = EXCLUDED.entp_name,
            class_name = EXCLUDED.class_name,
            ingredient = EXCLUDED.ingredient,
            indications = EXCLUDED.indications,
            dosage = EXCLUDED.dosage,
            warnings = EXCLUDED.warnings,
            interactions = EXCLUDED.interactions,
            side_effects = EXCLUDED.side_effects,
            updated_at = NOW();
    """

    payload: list[dict] = []
    skipped = 0
    for item in items:
        drug_id = _clean_text(item.get("itemSeq", item.get("ITEM_SEQ")))
        if not drug_id:
            continue
        if OTC_ONLY and not _is_otc_item(item):
            skipped += 1
            continue

        atpn_warn = _clean_text(item.get("atpnWarnQesitm", item.get("ATPN_WARN_QESITM")))
        atpn = _clean_text(item.get("atpnQesitm", item.get("ATPN_QESITM")))
        payload.append({
            "drug_id": drug_id,
            "name_ko": _clean_text(item.get("itemName", item.get("ITEM_NAME"))),
            "entp_name": _clean_text(item.get("entpName", item.get("ENTP_NAME"))),
            "class_name": _clean_text(item.get("className", item.get("CLASS_NAME"))),
            "ingredient": _clean_text(item.get("mainItemIngr", item.get("MAIN_ITEM_INGR"))),
            "indications": _clean_text(item.get("efcyQesitm", item.get("EFCY_QESITM"))),
            "dosage": _clean_text(item.get("useMethodQesitm", item.get("USE_METHOD_QESITM"))),
            "warnings": _clean_text(f"{atpn_warn} {atpn}".strip()),
            "interactions": _clean_text(item.get("intrcQesitm", item.get("INTRC_QESITM"))),
            "side_effects": _clean_text(item.get("seQesitm", item.get("SE_QESITM"))),
        })

    conn = set_client.get_db_conn()
    batch_size = 500
    try:
        with conn.cursor() as cur:
            for i in range(0, len(payload), batch_size):
                cur.executemany(upsert, payload[i : i + batch_size])
        conn.commit()
    finally:
        conn.close()

    if skipped:
        print(f"[*] 전문의약품 스킵: {skipped}건 (SILVER_OTC_ONLY={OTC_ONLY})", flush=True)
    print(f"[+] silver_drug_info 적재: {len(payload)}건", flush=True)
    return len(payload)


def _taboo_row(item: dict) -> dict | None:
    drug_a_id = _clean_text(item.get("ITEM_SEQ", item.get("itemSeq")))
    drug_b_id = _clean_text(item.get("MIXTURE_ITEM_SEQ", item.get("mixtureItemSeq")))
    if not drug_a_id or not drug_b_id:
        return None
    drug_b_ingr = _clean_text(
        item.get("MIXTURE_INGR_KOR_NAME", item.get("mixtureIngrKorName"))
    )
    return {
        "drug_id": drug_a_id,
        "drug_name": _clean_text(item.get("ITEM_NAME", item.get("itemName"))) or None,
        "mixture_drug_id": drug_b_id,
        "mixture_drug_name": _clean_text(
            item.get("MIXTURE_ITEM_NAME", item.get("mixtureItemName"))
        ) or None,
        "mixture_ingr_name": drug_b_ingr or None,
        "prohibited_content": _clean_text(
            item.get("PROHBT_CONTENT", item.get("prohbtContent"))
        ) or None,
    }


def import_taboo_from_part(part_path: Path) -> int:
    upsert = """
        INSERT INTO silver_taboo_info (
            drug_id, drug_name, mixture_drug_id, mixture_drug_name,
            mixture_ingr_name, prohibited_content
        ) VALUES (
            %(drug_id)s, %(drug_name)s, %(mixture_drug_id)s, %(mixture_drug_name)s,
            %(mixture_ingr_name)s, %(prohibited_content)s
        );
    """
    print(f"[+] taboo_info 스트리밍 import 시작: {part_path}", flush=True)

    conn = set_client.get_db_conn()
    inserted = 0
    batch: list[dict] = []
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE silver_taboo_info RESTART IDENTITY;")
            for item in iter_taboo_items_from_part(part_path):
                row = _taboo_row(item)
                if not row:
                    continue
                batch.append(row)
                if len(batch) >= TABOO_BATCH_SIZE:
                    cur.executemany(upsert, batch)
                    inserted += len(batch)
                    batch.clear()
                    if inserted % 50000 == 0:
                        print(f"    ... taboo {inserted:,}건", flush=True)
            if batch:
                cur.executemany(upsert, batch)
                inserted += len(batch)
        conn.commit()
    finally:
        conn.close()

    print(f"[+] silver_taboo_info 적재: {inserted:,}건", flush=True)
    return inserted


def print_summary() -> None:
    conn = set_client.get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM silver_symptom")
            sym = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM silver_drug_info")
            drug = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM silver_taboo_info")
            taboo = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM silver_drug_integration")
            integrated = cur.fetchone()[0]
        print(
            f"[+] Silver 요약: symptom={sym}, drug_info={drug}, taboo={taboo}, "
            f"integration_view={integrated}",
            flush=True,
        )
    finally:
        conn.close()


def main() -> None:
    print("[*] import_team_data.py 시작", flush=True)
    csv_path, drug_part = _require_paths()
    import_symptoms_from_csv(csv_path)
    import_drugs_from_part(drug_part)

    if SKIP_TABOO:
        print("[*] SKIP_TABOO=true — taboo import 생략", flush=True)
    else:
        taboo_part = find_latest_part(TEAM_TABOO_INFO_ROOT)
        if taboo_part is None:
            print("[!] taboo_info part.1 없음 — taboo import 생략", flush=True)
        else:
            import_taboo_from_part(taboo_part)

    print_summary()
    print("[+] 팀 데이터 Silver 적재 완료", flush=True)
    print("    다음: python src/vectordb/vectorizer.py", flush=True)
    print("    다음: python src/extractor/export_silver_to_ai.py", flush=True)


if __name__ == "__main__":
    main()
