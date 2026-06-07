"""팀원 로컬 데이터 → AI data/*.json (Docker/PostgreSQL 불필요).

database/data/msd_source + minio/bronze 를 읽어
프로젝트 루트 data/drugs.json, data/symptoms.json 을 생성합니다.

실행 (database 루트):
    python src/extractor/export_team_data_direct.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import pandas as pd
from export_silver_to_ai import _build_drug_record, _save_json, _symptom_core
from minio_part import extract_items_from_part, find_latest_part, iter_taboo_items_from_part
from paths import (
    AI_DRUGS_JSON,
    AI_SYMPTOMS_JSON,
    DATA_DIR,
    MSD_SOURCE_DIR,
    TEAM_DRUG_INFO_ROOT,
    TEAM_TABOO_INFO_ROOT,
)

SILVER_CSV = MSD_SOURCE_DIR / "silver_data.csv"
OTC_ONLY = os.getenv("SILVER_OTC_ONLY", "false").lower() in {"1", "true", "yes"}
SKIP_TABOO = os.getenv("SKIP_TABOO", "false").lower() in {"1", "true", "yes"}


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
    for key in ("etcOtcName", "ETC_OTC_CODE", "ETC_OTC_NAME", "etcOtcCode"):
        value = str(item.get(key) or "").strip()
        if not value:
            continue
        if "일반" in value or value.upper() in {"02", "OTC"}:
            return True
        if "전문" in value or value.upper() in {"01", "ETC"}:
            return False
    return True


def load_symptoms_from_csv(csv_path: Path) -> list[dict]:
    df = pd.read_csv(csv_path)
    print(f"[+] 증상 CSV: {len(df)}행", flush=True)
    records: list[dict] = []
    for _, row in df.iterrows():
        symptom_id = _clean_text(row.get("symptom_id"))
        name = _clean_text(row.get("name"))
        if not symptom_id or not name:
            continue
        core = _symptom_core(name) or name
        context = _clean_text(row.get("context")) or _clean_text(row.get("warning_sign"))
        records.append({
            "symptom_id": symptom_id,
            "name": core,
            "is_red_flag": _parse_bool(row.get("is_red_flag")),
            "urgency": None,
            "context": context or None,
            "action_guide": _clean_text(row.get("action_guide")) or None,
        })
    print(f"[+] 증상 JSON 후보: {len(records)}건", flush=True)
    return records


def load_drugs_from_part(part_path: Path, symptom_names: list[str]) -> list[dict]:
    items = extract_items_from_part(part_path)
    print(f"[+] drug_info part: {len(items)}건 ({part_path.name})", flush=True)
    records: list[dict] = []
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
        row = {
            "drug_id": drug_id,
            "name_ko": _clean_text(item.get("itemName", item.get("ITEM_NAME"))),
            "class_name": _clean_text(item.get("className", item.get("CLASS_NAME"))),
            "ingredient": _clean_text(item.get("mainItemIngr", item.get("MAIN_ITEM_INGR"))),
            "indications": _clean_text(item.get("efcyQesitm", item.get("EFCY_QESITM"))),
            "dosage": _clean_text(item.get("useMethodQesitm", item.get("USE_METHOD_QESITM"))),
            "warnings": _clean_text(f"{atpn_warn} {atpn}".strip()),
            "combination_contraindication": "",
        }
        if not row["name_ko"]:
            continue
        records.append(_build_drug_record(row, symptom_names))
    if skipped:
        print(f"[*] 전문의약품 스킵: {skipped}건", flush=True)
    print(f"[+] 약물 JSON 후보: {len(records)}건", flush=True)
    return records


def load_taboo_map(part_path: Path) -> dict[str, list[str]]:
    """drug_id → 병용금기 대상명 목록 (중복 제거, 삽입 순)."""
    buckets: dict[str, set[str]] = defaultdict(set)
    count = 0
    print(f"[+] taboo 스트리밍: {part_path}", flush=True)
    for item in iter_taboo_items_from_part(part_path):
        drug_id = _clean_text(item.get("ITEM_SEQ", item.get("itemSeq")))
        if not drug_id:
            continue
        label = _clean_text(
            item.get("MIXTURE_ITEM_NAME", item.get("mixtureItemName"))
        ) or _clean_text(
            item.get("MIXTURE_INGR_KOR_NAME", item.get("mixtureIngrKorName"))
        )
        if label:
            buckets[drug_id].add(label)
        count += 1
        if count % 100000 == 0:
            print(f"    ... taboo {count:,}행 처리", flush=True)
    result = {k: sorted(v) for k, v in buckets.items()}
    print(f"[+] taboo 집계: {count:,}행 → {len(result):,}약물", flush=True)
    return result


def merge_taboo(drugs: list[dict], taboo_map: dict[str, list[str]]) -> None:
    merged = 0
    for drug in drugs:
        extra = taboo_map.get(str(drug["drug_id"]), [])
        if not extra:
            continue
        existing = drug.get("combination_contraindication") or []
        combined = list(dict.fromkeys([*existing, *extra]))
        drug["combination_contraindication"] = combined
        merged += 1
    print(f"[+] 병용금기 merge: {merged}약물", flush=True)


def main() -> None:
    if not SILVER_CSV.exists():
        raise FileNotFoundError(f"증상 CSV 없음: {SILVER_CSV}")
    drug_part = find_latest_part(TEAM_DRUG_INFO_ROOT)
    if drug_part is None:
        raise FileNotFoundError(f"drug_info part.1 없음: {TEAM_DRUG_INFO_ROOT}")

    symptoms = load_symptoms_from_csv(SILVER_CSV)
    symptom_names = [s["name"] for s in symptoms]
    drugs = load_drugs_from_part(drug_part, symptom_names)

    if not SKIP_TABOO:
        taboo_part = find_latest_part(TEAM_TABOO_INFO_ROOT)
        if taboo_part is None:
            print("[!] taboo part 없음 — DUR 없이 진행", flush=True)
        else:
            taboo_map = load_taboo_map(taboo_part)
            merge_taboo(drugs, taboo_map)
    else:
        print("[*] SKIP_TABOO=true", flush=True)

    if not drugs:
        raise RuntimeError("export할 약물이 없습니다.")

    _save_json(AI_SYMPTOMS_JSON, symptoms)
    _save_json(AI_DRUGS_JSON, drugs)
    print(f"[+] Docker 없이 AI JSON export 완료", flush=True)
    print(f"    symptoms: {len(symptoms)} → {AI_SYMPTOMS_JSON}", flush=True)
    print(f"    drugs:    {len(drugs)} → {AI_DRUGS_JSON}", flush=True)
    print("[*] ChromaDB hybrid는 Docker 없으면 OFF (USE_CHROMA=false 권장)", flush=True)


if __name__ == "__main__":
    main()
