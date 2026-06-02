from __future__ import annotations

import json
from pathlib import Path

from cleaner import clean_drug_record, clean_symptom_record


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_dataset(raw_drug_path: str, raw_symptom_path: str, output_dir: str = "data/processed") -> None:
    raw_drugs = _load_json(Path(raw_drug_path))
    raw_symptoms = _load_json(Path(raw_symptom_path))

    cleaned_drugs = [clean_drug_record(item) for item in raw_drugs]
    cleaned_symptoms = [clean_symptom_record(item) for item in raw_symptoms]

    output = Path(output_dir)
    _save_json(output / "drugs_clean.json", cleaned_drugs)
    _save_json(output / "symptoms_clean.json", cleaned_symptoms)


if __name__ == "__main__":
    build_dataset("data/drugs.json", "data/symptoms.json")
