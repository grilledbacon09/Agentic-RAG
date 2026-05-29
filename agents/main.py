from __future__ import annotations

from pathlib import Path

from loader import load_drugs, load_symptoms
from agents.models import UserInput
from pipeline import run_pipeline


def parse_csv_input(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data"

    drugs = load_drugs(data_dir / "drugs.json")
    symptoms = load_symptoms(data_dir / "symptoms.json")

    print("=== 초기 정적 RAG 약 정보 응답 데모 ===")
    print("쉼표(,)로 여러 값을 입력할 수 있습니다.")
    print()

    symptom_list = parse_csv_input(input("증상 입력: "))
    current_drug_ids = parse_csv_input(input("현재 복용 중인 약 ID 입력 (예: D001,D002): "))
    current_drug_names = parse_csv_input(input("현재 복용 중인 약 이름 입력: "))
    allergies = parse_csv_input(input("알레르기 입력: "))
    conditions = parse_csv_input(input("기저질환/특이상태 입력: "))

    user_input = UserInput(
        symptoms=symptom_list,
        current_drug_ids=current_drug_ids,
        current_drug_names=current_drug_names,
        allergies=allergies,
        conditions=conditions,
    )

    result = run_pipeline(user_input, drugs, symptoms)

    print()
    print("=" * 60)
    print(result)
    print("=" * 60)


if __name__ == "__main__":
    main()