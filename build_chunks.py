from __future__ import annotations

import json
from pathlib import Path

from chunker import build_chunks


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> None:
    processed = Path("data/processed")
    drugs_path = processed / "drugs_clean.json"
    symptoms_path = processed / "symptoms_clean.json"

    if drugs_path.exists() and symptoms_path.exists():
        drugs = _load_json(drugs_path)
        symptoms = _load_json(symptoms_path)
    else:
        drugs = _load_json(Path("data/drugs.json"))
        symptoms = _load_json(Path("data/symptoms.json"))

    chunks = build_chunks(drugs, symptoms)
    _save_json(processed / "chunks.json", chunks)
    print(f"chunks saved: {len(chunks)}")


if __name__ == "__main__":
    main()
