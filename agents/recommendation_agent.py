from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from agents.reranker import RerankedResult


@dataclass
class RecommendationDecision:
    recommended: List[RerankedResult] = field(default_factory=list)
    rejected: List[RerankedResult] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)


def decide_recommendations(reranked_results: List[RerankedResult], max_recommendations: int = 3) -> RecommendationDecision:
    """재정렬 결과를 추천/비추천으로 나눈다."""

    recommended: List[RerankedResult] = []
    rejected: List[RerankedResult] = []
    messages: List[str] = []

    for item in reranked_results:
        if item.blocked or item.risk_level == "high" or item.final_score <= 0:
            rejected.append(item)
        elif len(recommended) < max_recommendations:
            recommended.append(item)
        else:
            rejected.append(item)

    if recommended:
        top = recommended[0].retrieval.drug
        messages.append(f"최종 1순위 후보는 {top.name_ko}입니다.")
    else:
        messages.append("안전성 기준을 통과한 추천 후보가 없습니다. 약사/의료진 상담이 필요합니다.")

    if rejected:
        messages.append(f"안전성 또는 낮은 관련성으로 제외된 후보 {len(rejected)}개가 있습니다.")

    return RecommendationDecision(recommended=recommended, rejected=rejected, messages=messages)
