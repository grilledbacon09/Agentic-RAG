from __future__ import annotations

from agents.config import load_config
from agents.enhanced_pipeline import run_enhanced_pipeline
from agents.loader import load_drugs, load_symptoms
from agents.query_agent import analyze_query


def main() -> None:
    config = load_config()
    drugs = load_drugs(config.data_dir / "drugs.json")
    symptoms = load_symptoms(config.data_dir / "symptoms.json")

    print("=== 확장 Agentic RAG 단답형 데모 (레거시) ===")
    print("ChatGPT형 대화 UI: python chat_web.py")
    print(f"데이터: {config.data_dir}")
    print(f"ChromaDB hybrid retrieval: {'ON' if config.use_chroma else 'OFF'}")
    print("쉼표(,)로 여러 값을 입력할 수 있습니다.\n")

    analysis = analyze_query(
        raw_symptoms=input("증상 입력: "),
        raw_current_drug_ids=input("현재 복용 중인 약 ID 입력 (예: D001,D002): "),
        raw_current_drug_names=input("현재 복용 중인 약 이름 입력: "),
        raw_allergies=input("알레르기 입력: "),
        raw_conditions=input("기저질환/특이상태 입력: "),
        drugs=drugs,
        symptoms=symptoms,
    )

    result = run_enhanced_pipeline(
        analysis.user_input,
        drugs,
        symptoms,
        top_k=config.top_k,
        config=config,
    )

    print("\n" + "=" * 70)
    print(result)
    print("=" * 70)


if __name__ == "__main__":
    main()
