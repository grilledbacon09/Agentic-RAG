"""
[GRAPH 2] Knowledge Graph 조회 도구 (AI 파트 연동용)

AI Agent가 호출하는 '결정적 안전 검사' 함수 모음입니다.
  - 그래프(Neo4j)는 "먹어도 되는가"를 판정하고
  - 벡터 DB(dur_ingredient 문서)는 "왜 안 되는가"를 설명합니다.

함수 목록
  find_drug(query)                        제품명 / 바코드 / 품목기준코드 → 제품 후보
  check_status(item_seq)                  성분 정보 유무 (UNKNOWN 판정) + 성분·용량 정보
  check_interactions(current, candidate)  병용금기 + 동일 성분 중복 + 효능군 중복 (복용약 ↔ 후보약)
  check_current(current)                  복용 중인 약끼리의 병용금기·성분 중복
  check_profile(candidate, ...)           임부 / 소아(나이) / 노인 제한
  get_subgraph(current, candidate)        WEB 그래프 출력용 노드·엣지 JSON
  assess(current, candidate, ...)         위 검사를 모두 묶은 최종 판정 ★ Agent는 이것만 써도 됨

판정 원칙
  - 성분 정보가 없는 제품은 '안전'이 아니라 UNKNOWN
  - 'OK'는 "식약처 DUR 기준 금기·주의 없음"이지 의학적 안전 보장이 아님
  - 사유가 원본에 없으면 지어내지 않고 빈값으로 반환 (화면에서 유형 기본 문구 사용)
  - 특정 제형(서방정 등)에만 해당하는 성분 금기는 DUR 품목정보의 제품 지정 / 제품명으로 확인 후 적용

사용법
  from graph_tools import DrugGraph
  g = DrugGraph()                                   # .env의 NEO4J_URI / USER / PASSWORD 사용
  g.find_drug("리피스탄")
  g.assess(current=["200402374"], candidate="200000913", age=35, pregnant=False)
  g.close()

  python graph_tools.py                             # 동작 확인 (코니트라캡슐 vs 리피스탄정)
"""
import json
import os
import re
from pathlib import Path

from neo4j import GraphDatabase

try:  # 이 파일 위치 기준 config/.env (없으면 이미 설정된 환경변수 사용)
    from dotenv import load_dotenv
    for p in Path(__file__).resolve().parents:
        if (p / "config" / ".env").exists():
            load_dotenv(p / "config" / ".env")
            break
except ImportError:
    pass

DISCLAIMER = "식약처 DUR 기준의 금기·주의 검사 결과이며, 복용 전 약사·의사와 상담하세요."
MINOR_AGE = 19          # 연령 기준을 모르는 소아 금기를 보수적으로 적용할 나이 (만 19세 미만)
ELDERLY_AGE = 65

# 판정 우선순위 (큰 값이 더 심각)
VERDICT_RANK = {"OK": 0, "CAUTION": 1, "UNKNOWN": 2, "BAN": 3, "NOT_FOUND": 4}

# 특수 제형 키워드 → 제품명에서 찾을 별칭
# 성분 금기의 제형 목록이 '전부' 특수 제형이면 그 제형에만 해당하는 금기로 본다
SPECIAL_FORMS = {
    "서방": ["서방", "이알"],
    "장용": ["장용"],
    "주사": ["주사"],
    "점안": ["점안"],
    "점이": ["점이"],
    "점비": ["점비"],
    "좌": ["좌제", "좌약"],
    "흡입": ["흡입"],
    "패": ["패취", "패치"],
    "연고": ["연고"],
    "크림": ["크림"],
    "겔": ["겔"],
    "외용": ["외용"],
}


def form_keywords(forms: list[str] | None) -> set[str] | None:
    """제형 제한이 '특수 제형만'이면 해당 키워드 집합, 아니면 None (모든 제형에 적용)
    예) ['서방정/서방성필름코팅정/서방성당의정']  → {'서방'}
        ['정제'], ['연질캡슐제, 현탁상/유화주사제'] → None (일반 제형이 섞여 있음 → 보수적으로 전체 적용)
    """
    tokens = [t.strip() for f in (forms or []) for t in re.split(r"[/,]", f) if t.strip()]
    if not tokens:
        return None
    keys = set()
    for t in tokens:
        hit = [k for k in SPECIAL_FORMS if k in t]
        if not hit:
            return None
        keys.update(hit)
    return keys


# 같은 성분인데 원료 표기만 다른 경우 (예: '아세트아미노펜 제피세립', '아세트아미노펜(미분화)')
# → 표기를 떼고 비교해서 성분 중복으로 판정. 염(염산염 등)은 성분이 달라질 수 있어 떼지 않음
FORM_WORDS = ["코팅과립", "제피세립", "직타용", "미분화", "미립자", "과립", "세립", "분말", "결정"]
_FORM_RE = re.compile("|".join(sorted(FORM_WORDS, key=len, reverse=True)))


def canon_ingredient(name: str | None) -> str:
    """성분 비교용 이름: 공백·괄호·원료 표기 제거  '아세트아미노펜 제피세립' → '아세트아미노펜'"""
    n = re.sub(r"\s+", "", name or "")
    n = re.sub(r"[\(\[]([^\)\]]*)[\)\]]", lambda m: "" if _FORM_RE.fullmatch(m.group(1)) else m.group(0), n)
    n = _FORM_RE.sub("", n)
    return n


# 유형별 기본 문구 (원본에 사유가 없을 때 화면 표시용)
DEFAULT_MESSAGE = {
    "contraindication": "함께 복용하면 안 되는 성분 조합입니다 (식약처 병용금기).",
    "duplicate_ingredient": "같은 성분이 중복됩니다. 함께 먹으면 과다 복용 위험이 있습니다.",
    "current_contraindication": "지금 함께 복용 중인 약끼리 병용금기 성분이 있습니다. 약사·의사와 상담하세요.",
    "current_duplicate": "지금 복용 중인 약끼리 같은 성분이 중복됩니다. 1일 총 복용량을 확인하세요.",
    "effect_duplicate": "같은 효능군의 약입니다. 함께 먹으면 효과·부작용이 겹칠 수 있습니다.",
    "PREGNANT": "임부에게 사용을 피해야 하는 성분입니다 (식약처 임부금기).",
    "PEDIATRIC": "해당 연령에 사용을 피해야 하는 성분입니다 (식약처 특정연령대금기).",
    "ELDERLY": "노인에게 주의가 필요한 성분입니다 (식약처 노인주의).",
}


# ─────────────────────────────────────
# Cypher
# ─────────────────────────────────────
Q_FIND = """
MATCH (d:Drug)
WHERE ($barcode IS NOT NULL AND $barcode IN d.bar_codes)
   OR ($seq IS NOT NULL AND d.item_seq = $seq)
   OR ($name IS NOT NULL AND replace(d.name, ' ', '') CONTAINS $name)
RETURN d.item_seq AS item_seq, d.name AS name, d.manufacturer AS manufacturer,
       d.etc_otc AS etc_otc, d.is_otc AS is_otc, d.is_active AS is_active
ORDER BY CASE WHEN replace(d.name, ' ', '') = $name THEN 0 ELSE 1 END,
         d.is_active DESC, d.is_otc DESC, size(d.name)
LIMIT $limit
"""

Q_STATUS = """
MATCH (d:Drug {item_seq: $seq})
OPTIONAL MATCH (d)-[c:CONTAINS]->(i:Ingredient)
RETURN d {.item_seq, .name, .manufacturer, .etc_otc, .is_otc, .is_active, .official_url} AS drug,
       collect(CASE WHEN i IS NULL THEN NULL ELSE {
           code: i.code, name: i.name_kor, name_eng: i.name_eng, in_dur: i.in_dur,
           amount: c.amount, unit: c.unit,
           dose_limits: i.dose_limits, term_limits: i.term_limits
       } END) AS ingredients
"""

Q_INTERACTIONS = """
MATCH (cand:Drug {item_seq: $candidate})-[:CONTAINS]->(ki:Ingredient)-[e:CONTRAINDICATED_WITH]-(ci:Ingredient)
      <-[:CONTAINS]-(cur:Drug)
WHERE cur.item_seq IN $current AND cur.item_seq <> $candidate
RETURN DISTINCT 'contraindication' AS type,
       cur.item_seq AS current_seq, cur.name AS current_drug,
       ci.code AS current_code, ci.name_kor AS current_ingredient,
       ki.code AS candidate_code, ki.name_kor AS candidate_ingredient,
       e.latest_reason AS reason, e.reasons AS reasons, e.conditions AS conditions,
       e.source AS source, e.source_url AS source_url
"""

# 약 목록 안의 모든 약 쌍(a < b) 사이 병용금기 (복용약끼리 검사 + 그래프용)
Q_PAIR_CONTRA = """
MATCH (a:Drug)-[:CONTAINS]->(ia:Ingredient)-[e:CONTRAINDICATED_WITH]-(ib:Ingredient)<-[:CONTAINS]-(b:Drug)
WHERE a.item_seq IN $seqs AND b.item_seq IN $seqs AND a.item_seq < b.item_seq
RETURN DISTINCT a.item_seq AS a_seq, a.name AS a_drug, ia.code AS a_code, ia.name_kor AS a_ingredient,
       b.item_seq AS b_seq, b.name AS b_drug, ib.code AS b_code, ib.name_kor AS b_ingredient,
       e.latest_reason AS reason, e.reasons AS reasons, e.conditions AS conditions,
       e.source AS source, e.source_url AS source_url
"""

Q_EFFECT_DUP = """
MATCH (cand:Drug {item_seq: $candidate})-[:CONTAINS]->(ki:Ingredient)-[r1:BELONGS_TO]->(g:EffectGroup)
      <-[r2:BELONGS_TO]-(ci:Ingredient)<-[:CONTAINS]-(cur:Drug)
WHERE cur.item_seq IN $current AND cur.item_seq <> $candidate AND ci <> ki
RETURN DISTINCT 'effect_duplicate' AS type,
       cur.item_seq AS current_seq, cur.name AS current_drug,
       ci.code AS current_code, ci.name_kor AS current_ingredient,
       ki.code AS candidate_code, ki.name_kor AS candidate_ingredient,
       g.name AS effect_group, r1.source AS source, r1.source_url AS source_url
"""

Q_PROFILE = """
MATCH (d:Drug {item_seq: $candidate})-[:CONTAINS]->(i:Ingredient)-[r:RESTRICTED_FOR]->(g:PatientGroup)
OPTIONAL MATCH (d)-[f:DUR_FLAGGED]->(g)
RETURN DISTINCT i.code AS code, i.name_kor AS ingredient, d.name AS drug_name,
       (f IS NOT NULL AND i.code IN f.ingr_codes) AS product_flagged,
       g.code AS group, g.name AS group_name, r.level AS level,
       r.pregnancy_grade AS pregnancy_grade, r.max_age_months AS max_age_months,
       r.age_unknown AS age_unknown, r.age_bases AS age_bases,
       r.reasons AS reasons, r.remarks AS remarks, r.forms AS forms,
       r.source AS source, r.source_url AS source_url
"""

Q_SUB_DRUGS = """
MATCH (d:Drug) WHERE d.item_seq IN $seqs
OPTIONAL MATCH (d)-[:CONTAINS]->(i:Ingredient)
RETURN d.item_seq AS item_seq, d.name AS name, d.etc_otc AS etc_otc,
       collect(CASE WHEN i IS NULL THEN NULL ELSE {code: i.code, name: i.name_kor, in_dur: i.in_dur,
               has_limit: size(coalesce(i.dose_limits, [])) > 0 OR size(coalesce(i.term_limits, [])) > 0} END) AS ingredients
"""



# ─────────────────────────────────────
# 조회 클래스
# ─────────────────────────────────────
class DrugGraph:
    def __init__(self, uri: str | None = None, user: str | None = None, password: str | None = None):
        self.driver = GraphDatabase.driver(
            uri or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(user or os.getenv("NEO4J_USER", "neo4j"), password or os.getenv("NEO4J_PASSWORD", "")),
        )

    def close(self):
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _run(self, query: str, **params) -> list[dict]:
        with self.driver.session() as s:
            return s.run(query, **params).data()

    # ── 1. 제품 찾기 ───────────────────────
    def find_drug(self, query: str, limit: int = 10, otc_only: bool = False) -> list[dict]:
        """제품명(부분 일치) / 바코드(13자리) / 품목기준코드(9자리) → 제품 후보 목록
        정렬: 이름 완전 일치 → 허가 유효 → 일반의약품 → 이름이 짧은 순
        otc_only=False(기본): 복용 중인 약 입력용 — 전문의약품도 찾아야 금기 검사가 됨
        otc_only=True       : 추천·안내할 약을 찾을 때 — 허가 유효한 일반의약품만
        """
        q = re.sub(r"\s+", "", query or "")
        if not q:
            return []
        barcode = q if re.fullmatch(r"\d{13}", q) else None
        seq = q if re.fullmatch(r"\d{9}", q) else None
        name = None if (barcode or seq) else q
        rows = self._run(Q_FIND, barcode=barcode, seq=seq, name=name, limit=limit * (5 if otc_only else 1))
        if otc_only:
            rows = [r for r in rows if r.get("is_otc") and r.get("is_active")]
        return rows[:limit]

    # ── 2. 성분 정보 유무 ──────────────────
    def check_status(self, item_seq: str) -> dict:
        """status: NOT_FOUND(제품 없음) / UNKNOWN(성분 정보 없음) / CHECKABLE(검사 가능)"""
        rows = self._run(Q_STATUS, seq=item_seq)
        if not rows:
            return {"item_seq": item_seq, "status": "NOT_FOUND", "drug": None, "ingredients": []}
        drug, ingredients = rows[0]["drug"], rows[0]["ingredients"]
        return {
            "item_seq": item_seq,
            "status": "CHECKABLE" if ingredients else "UNKNOWN",
            "drug": drug,
            "ingredients": ingredients,
        }

    # ── 3. 복용약과의 상호작용 ─────────────
    def _drug_ingredients(self, seqs: list[str]) -> dict[str, dict]:
        """item_seq → {item_seq, name, etc_otc, ingredients: [{code, name, in_dur, has_limit}]}"""
        return {d["item_seq"]: d for d in self._run(Q_SUB_DRUGS, seqs=list(dict.fromkeys(seqs)))}

    @staticmethod
    def _dup_pairs(ingr_a: list[dict], ingr_b: list[dict], all_duplicates: bool = False) -> list[tuple[dict, dict]]:
        """두 약에서 같은 성분 쌍 찾기: 성분 코드가 같거나, 원료 표기를 뗀 성분명이 같으면 중복
        기본은 DUR 대상 성분 또는 1일 최대투여량·투여기간 제한이 있는 성분만 (비타민·생약 조합 경고 남발 방지)"""
        out, seen = [], set()
        for x in ingr_a:
            for y in ingr_b:
                same = x["code"] == y["code"] or (canon_ingredient(x["name"]) and
                                                  canon_ingredient(x["name"]) == canon_ingredient(y["name"]))
                if not same:
                    continue
                important = any(i.get("in_dur") or i.get("has_limit") for i in (x, y))
                key = canon_ingredient(x["name"]) or x["code"]
                if (important or all_duplicates) and key not in seen:
                    seen.add(key)
                    out.append((x, y))
        return out

    def check_interactions(self, current: list[str], candidate: str,
                           all_duplicates: bool = False) -> list[dict]:
        """복용 중인 약(current)과 후보약(candidate) 사이의 문제
        - contraindication     : 병용금기 (ban)
        - duplicate_ingredient : 같은 성분 중복 (caution) — 성분 코드 또는 정규화한 성분명이 같으면 중복
                                 기본은 DUR 대상·용량 제한 성분만 (비타민 등 제외), all_duplicates=True면 전부
        - effect_duplicate     : 같은 효능군 (caution)
        """
        current = [c for c in current if c and c != candidate]
        if not current:
            return []
        rows = self._run(Q_INTERACTIONS, current=current, candidate=candidate)

        drugs = self._drug_ingredients([*current, candidate])
        cand_ingr = (drugs.get(candidate) or {}).get("ingredients", [])
        dup_names = set()
        for seq in current:
            cur = drugs.get(seq)
            if not cur:
                continue
            for ci, ki in self._dup_pairs(cur["ingredients"], cand_ingr, all_duplicates):
                dup_names.add((seq, canon_ingredient(ki["name"])))
                rows.append({"type": "duplicate_ingredient",
                             "current_seq": seq, "current_drug": cur["name"],
                             "current_code": ci["code"], "current_ingredient": ci["name"],
                             "candidate_code": ki["code"], "candidate_ingredient": ki["name"],
                             "reason": None, "reasons": None, "conditions": None,
                             "source": "성분 비교 (식약처 허가정보 주성분)", "source_url": None})

        for r in self._run(Q_EFFECT_DUP, current=current, candidate=candidate):
            # 같은 성분이라 이미 '성분 중복'으로 잡힌 건 효능군 중복으로 다시 넣지 않음
            if (r["current_seq"], canon_ingredient(r["candidate_ingredient"])) in dup_names \
                    and canon_ingredient(r["current_ingredient"]) == canon_ingredient(r["candidate_ingredient"]):
                continue
            rows.append(r)
        for r in rows:
            r["level"] = "ban" if r["type"] == "contraindication" else "caution"
            r["message"] = r.get("reason") or DEFAULT_MESSAGE[r["type"]]
        return rows

    def check_current(self, current: list[str], all_duplicates: bool = False) -> list[dict]:
        """복용 중인 약끼리의 문제 (후보약과 상관없이 이미 함께 먹고 있는 조합)
        - current_contraindication : 병용금기 (ban)
        - current_duplicate        : 같은 성분 중복 (caution) — 예: 타이레놀 + 게보린 (아세트아미노펜)
        반환 키: type, drug_a_seq, drug_a, ingredient_a, code_a, drug_b_seq, drug_b, ingredient_b, code_b, level, message
        """
        current = list(dict.fromkeys(c for c in current if c))
        if len(current) < 2:
            return []
        out = []
        for r in self._run(Q_PAIR_CONTRA, seqs=current):
            out.append({"type": "current_contraindication",
                        "drug_a_seq": r["a_seq"], "drug_a": r["a_drug"], "code_a": r["a_code"], "ingredient_a": r["a_ingredient"],
                        "drug_b_seq": r["b_seq"], "drug_b": r["b_drug"], "code_b": r["b_code"], "ingredient_b": r["b_ingredient"],
                        "reason": r["reason"], "reasons": r["reasons"], "conditions": r["conditions"],
                        "source": r["source"], "source_url": r["source_url"], "level": "ban",
                        "message": r["reason"] or DEFAULT_MESSAGE["current_contraindication"]})
        drugs = self._drug_ingredients(current)
        for i, sa in enumerate(current):
            for sb in current[i + 1:]:
                da, db = drugs.get(sa), drugs.get(sb)
                if not (da and db):
                    continue
                for x, y in self._dup_pairs(da["ingredients"], db["ingredients"], all_duplicates):
                    out.append({"type": "current_duplicate",
                                "drug_a_seq": sa, "drug_a": da["name"], "code_a": x["code"], "ingredient_a": x["name"],
                                "drug_b_seq": sb, "drug_b": db["name"], "code_b": y["code"], "ingredient_b": y["name"],
                                "reason": None, "source": "성분 비교 (식약처 허가정보 주성분)", "source_url": None,
                                "level": "caution", "message": DEFAULT_MESSAGE["current_duplicate"]})
        return out

    # ── 4. 환자군 제한 ────────────────────
    def check_profile(self, candidate: str, age: float | None = None,
                      pregnant: bool = False) -> list[dict]:
        """임부 / 소아 / 노인 제한. 각 항목의 applies:
           True  = 이 사용자에게 해당
           False = 해당하지 않음 (예: 성인에게 소아 금기)
           None  = 판단 불가 (나이를 모름) → Agent가 나이를 다시 물어볼 것

        제형 조건 (form_check):
           all_forms       성분 금기가 모든 제형에 해당 → 성분 기준으로 적용
           product_flagged DUR 품목정보가 이 제품을 직접 지정 → 적용
           name_match      제품명에 해당 제형(예: '서방')이 있음 → 적용
           not_matched     특수 제형에만 해당하는 금기인데 이 제품은 해당 없음 → applies=False
        """
        results = []
        for r in self._run(Q_PROFILE, candidate=candidate):
            r["form_check"] = self._form_check(r)
            if r["form_check"] == "not_matched":
                r["applies"] = False
            else:
                r["applies"] = self._applies(r, age, pregnant)
            r["message"] = "; ".join(r.get("reasons") or []) or DEFAULT_MESSAGE[r["group"]]
            results.append(r)
        return results

    @staticmethod
    def _form_check(r: dict) -> str:
        keys = form_keywords(r.get("forms"))
        if keys is None:
            return "all_forms"
        if r.get("product_flagged"):
            return "product_flagged"
        name = re.sub(r"\s+", "", r.get("drug_name") or "")
        if any(alias in name for k in keys for alias in SPECIAL_FORMS[k]):
            return "name_match"
        return "not_matched"

    @staticmethod
    def _applies(r: dict, age: float | None, pregnant: bool) -> bool | None:
        group = r["group"]
        if group == "PREGNANT":
            return bool(pregnant)
        if group == "ELDERLY":
            return None if age is None else age >= ELDERLY_AGE
        if group == "PEDIATRIC":
            if age is None:
                return None
            months = age * 12
            hit_known = r.get("max_age_months") is not None and months < r["max_age_months"]
            hit_unknown = bool(r.get("age_unknown")) and age < MINOR_AGE   # 연령 기준 미상 → 미성년자 전체에 보수적 적용
            return hit_known or hit_unknown
        return None

    # ── 5. WEB 그래프 출력용 ───────────────
    def get_subgraph(self, current: list[str], candidate: str | None = None, dur_only: bool = False,
                     all_duplicates: bool = False) -> dict:
        """프론트엔드 그래프 라이브러리(vis-network, Cytoscape 등)에 바로 넣을 수 있는 형태
        nodes: [{id, type: Drug|Ingredient, label, role: current|candidate, highlight, issues}]
        edges: [{source, target, type, label, highlight}]
          type = CONTAINS               제품 → 성분 (금기·중복에 걸린 연결은 highlight=True)
                 CONTRAINDICATED_WITH   성분 ↔ 성분 병용금기 (복용약끼리도 포함)
                 DUPLICATE_INGREDIENT   코드는 다르지만 같은 성분 (예: 아세트아미노펜 ↔ 아세트아미노펜 제피세립)
        같은 성분 코드를 두 약 이상이 가지면 그 성분 노드 하나에 여러 약이 연결되고, issues에 'duplicate'가 붙음
        issues: ['contraindication'] / ['duplicate'] / 둘 다 / []
        dur_only=True면 DUR 대상 성분과 문제가 있는 성분만 표시 (생약 복합제처럼 성분이 많을 때)
        """
        seqs = list(dict.fromkeys([*current, *([candidate] if candidate else [])]))
        drugs = self._drug_ingredients(seqs)
        contra = self._run(Q_PAIR_CONTRA, seqs=seqs)

        # 문제 성분 표시
        issues: dict[str, set] = {}
        for e in contra:
            for c in (e["a_code"], e["b_code"]):
                issues.setdefault(c, set()).add("contraindication")
        dup_links = []                                  # (code_x, code_y) 코드가 다른 중복
        for i, sa in enumerate(seqs):
            for sb in seqs[i + 1:]:
                da, db = drugs.get(sa), drugs.get(sb)
                if not (da and db):
                    continue
                for x, y in self._dup_pairs(da["ingredients"], db["ingredients"], all_duplicates):
                    issues.setdefault(x["code"], set()).add("duplicate")
                    issues.setdefault(y["code"], set()).add("duplicate")
                    if x["code"] != y["code"]:
                        dup_links.append(tuple(sorted((x["code"], y["code"]))))

        nodes, edges, seen = [], [], set()
        for seq in seqs:
            d = drugs.get(seq)
            if not d:
                continue
            did = f"drug:{seq}"
            has_issue = any(i["code"] in issues for i in d["ingredients"])
            nodes.append({"id": did, "type": "Drug", "label": d["name"], "etc_otc": d["etc_otc"],
                          "role": "candidate" if seq == candidate else "current",
                          "highlight": has_issue, "issues": sorted({x for i in d["ingredients"] for x in issues.get(i["code"], ())})})
            for i in d["ingredients"]:
                if dur_only and not i["in_dur"] and i["code"] not in issues:
                    continue
                iid = f"ingr:{i['code']}"
                if iid not in seen:
                    seen.add(iid)
                    nodes.append({"id": iid, "type": "Ingredient", "label": i["name"], "role": None,
                                  "highlight": i["code"] in issues, "issues": sorted(issues.get(i["code"], ()))})
                edges.append({"source": did, "target": iid, "type": "CONTAINS", "label": "",
                              "highlight": i["code"] in issues})
        for e in contra:
            edges.append({"source": f"ingr:{e['a_code']}", "target": f"ingr:{e['b_code']}",
                          "type": "CONTRAINDICATED_WITH", "label": e["reason"] or "병용금기",
                          "conditions": e["conditions"] or [], "highlight": True})
        for x, y in dict.fromkeys(dup_links):
            edges.append({"source": f"ingr:{x}", "target": f"ingr:{y}", "type": "DUPLICATE_INGREDIENT",
                          "label": "같은 성분", "highlight": True})
        return {"nodes": nodes, "edges": edges}

    # ── 6. 종합 판정 ──────────────────────
    def assess(self, current: list[str], candidate: str, age: float | None = None,
               pregnant: bool = False, with_graph: bool = False) -> dict:
        """후보약을 먹어도 되는지 한 번에 판정
        verdict: NOT_FOUND > BAN > UNKNOWN > CAUTION > OK
          BAN       병용금기, 해당하는 임부·소아 금기
          UNKNOWN   후보약 성분 정보 없음 → 추천 제외 또는 약사 확인 안내
          CAUTION   성분 중복, 효능군 중복, 노인주의, 나이를 몰라 판단 불가, 복용약 성분 미확인
          OK        식약처 DUR 기준 금기·주의 없음 (안전 보장 아님)
        current_warnings: 복용 중인 약끼리의 병용금기·성분 중복 (후보약 판정과 별개, notes에도 안내 문구)
        """
        status = self.check_status(candidate)
        result = {
            "candidate": status["drug"] or {"item_seq": candidate},
            "verdict": "OK",
            "findings": [],
            "notes": [],
            "disclaimer": DISCLAIMER,
        }

        def raise_to(v: str):
            if VERDICT_RANK[v] > VERDICT_RANK[result["verdict"]]:
                result["verdict"] = v

        if status["status"] == "NOT_FOUND":
            raise_to("NOT_FOUND")
            result["notes"].append("해당 품목기준코드의 제품을 찾을 수 없습니다.")
            return result
        if status["status"] == "UNKNOWN":
            raise_to("UNKNOWN")
            result["notes"].append("이 제품은 성분 정보가 없어 금기 여부를 확인할 수 없습니다. 약사에게 확인하세요.")
        drug = status["drug"]
        if not drug.get("is_active"):
            result["notes"].append("허가가 취소·취하된 제품입니다.")
        if not drug.get("is_otc"):
            result["notes"].append("전문의약품으로, 일반의약품 추천 대상이 아닙니다.")

        # 복용약 중 성분 정보가 없는 약이 있으면 검사가 불완전함을 알림
        for seq in current:
            st = self.check_status(seq)
            if st["status"] != "CHECKABLE":
                raise_to("CAUTION")
                name = (st["drug"] or {}).get("name", seq)
                result["notes"].append(f"복용 중인 '{name}'은(는) 성분 정보가 없어 상호작용을 확인하지 못했습니다.")

        result["current_warnings"] = self.check_current(current)
        for w in result["current_warnings"]:
            what = "병용금기" if w["type"] == "current_contraindication" else "성분 중복"
            result["notes"].append(f"지금 복용 중인 '{w['drug_a']}'와(과) '{w['drug_b']}'은(는) {what}입니다"
                                   f" ({w['ingredient_a']}{'' if w['ingredient_a'] == w['ingredient_b'] else ' + ' + w['ingredient_b']})."
                                   " 후보약과 별개로 약사·의사와 확인하세요.")

        for f in self.check_interactions(current, candidate):
            result["findings"].append(f)
            raise_to("BAN" if f["level"] == "ban" else "CAUTION")

        for p in self.check_profile(candidate, age=age, pregnant=pregnant):
            if p["form_check"] == "not_matched":
                result["notes"].append(
                    f"{p['ingredient']}의 {p['group_name']} 금기는 다른 제형({', '.join(p['forms'])})에만 해당하여 이 제품에는 적용하지 않았습니다.")
                continue
            if p["applies"] is False:
                continue
            p["type"] = "restriction"
            result["findings"].append(p)
            if p["applies"] is None:
                raise_to("CAUTION")
                result["notes"].append(f"{p['group_name']} 관련 제한이 있어 나이 확인이 필요합니다.")
            else:
                raise_to("BAN" if p["level"] == "ban" else "CAUTION")

        if result["verdict"] == "OK":
            result["notes"].append("후보약은 식약처 DUR 기준으로 확인된 금기·주의가 없습니다."
                                   if result["current_warnings"] else "식약처 DUR 기준으로 확인된 금기·주의가 없습니다.")
        if with_graph:
            result["graph"] = self.get_subgraph(current, candidate)
        return result


# ─────────────────────────────────────
# 동작 확인
# ─────────────────────────────────────
if __name__ == "__main__":
    def show(title, obj):
        print(f"\n=== {title} ===")
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str)[:2500])

    with DrugGraph() as g:
        konitra = g.find_drug("코니트라", limit=3)
        lipistan = g.find_drug("리피스탄", limit=3)
        show("find_drug('코니트라')", konitra)
        show("find_drug('리피스탄')", lipistan)

        if konitra and lipistan:
            cur, cand = [lipistan[0]["item_seq"]], konitra[0]["item_seq"]
            show("check_status(코니트라)", g.check_status(cand))
            show("check_interactions(리피스탄 복용 중 → 코니트라)", g.check_interactions(cur, cand))
            show("assess(나이 35, 임신 X, 그래프 포함)",
                 g.assess(cur, cand, age=35, pregnant=False, with_graph=True))

        tylenol = g.find_drug("타이레놀", limit=1)
        if tylenol:
            show("assess(타이레놀, 7세 아이, 복용약 없음)", g.assess([], tylenol[0]["item_seq"], age=7))

        # 같은 성분(아세트아미노펜) 중복: 복용약끼리 + 후보약
        tylenol500 = g.find_drug("타이레놀정500", limit=1)
        geborin = g.find_drug("게보린브이정", limit=1)
        womens = g.find_drug("우먼스타이레놀정", limit=1)
        if tylenol500 and geborin and womens:
            r = g.assess([tylenol500[0]["item_seq"], geborin[0]["item_seq"]], womens[0]["item_seq"],
                         age=30, with_graph=True)
            show("assess(타이레놀정500 + 게보린브이정 복용 중 → 우먼스타이레놀정)",
                 {k: r[k] for k in ("verdict", "findings", "current_warnings", "notes")})
            show("graph (issues가 있는 노드와 강조된 연결)",
                 {"nodes": [n for n in r["graph"]["nodes"] if n["issues"]],
                  "edges": [e for e in r["graph"]["edges"] if e["highlight"]]})
