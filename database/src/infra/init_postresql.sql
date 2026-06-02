-- =====================================================================
-- Medical Drug Recommendation Service - PostgreSQL DDL
-- =====================================================================
-- 실행 순서:
--   1. bronze_metadata
--   2. silver_symptom
--   3. silver_drug_info
--   4. silver_taboo_info
--   5. silver_drug_final
--   6. silver_drug_integration (view)
-- =====================================================================


-- =====================================================================
-- [1] bronze_metadata
-- MinIO에 저장된 원본 파일의 수집 이력 관리
-- api_collector.py가 수집 완료 후 기록
-- =====================================================================
CREATE TABLE IF NOT EXISTS bronze_metadata (
    id              SERIAL          PRIMARY KEY,
    source          VARCHAR(50)     NOT NULL,               -- 'dur' | 'approved_drug' | 'drug_info'
    bucket          VARCHAR(100)    NOT NULL,               -- MinIO 버킷명 (예: bronze)
    file_key        VARCHAR(300)    NOT NULL,               -- MinIO 오브젝트 키 (예: dur_data.json)
    row_count       INTEGER,                                -- 수집된 레코드 수
    status          VARCHAR(20)     DEFAULT 'success',      -- 'success' | 'failed'
    error_message   TEXT,
    collected_at    TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bronze_metadata_source
    ON bronze_metadata(source);
CREATE INDEX IF NOT EXISTS idx_bronze_metadata_collected_at
    ON bronze_metadata(collected_at);


-- =====================================================================
-- [2] silver_symptom
-- MSD 매뉴얼에서 파싱한 증상 정보
-- msd_save_to_silver.py (규칙 기반) 또는
-- msd_exctractor.py (AI 기반) 가 upsert
-- =====================================================================
CREATE TABLE IF NOT EXISTS silver_symptom (
    symptom_id          VARCHAR(10)     PRIMARY KEY,        -- 'S001' 형태
    name                TEXT            NOT NULL,           -- 증상명 (동의어 포함)
    category            VARCHAR(100),                       -- 증상 카테고리 (예: 소화기, 신경과)
    is_red_flag         BOOLEAN         DEFAULT FALSE,      -- 즉시 병원 방문 필요 여부
    cause               TEXT,                               -- 증상 원인
    warning_sign        TEXT,                               -- 경고 징후
    meet_doc            TEXT,                               -- 의사 진찰이 필요한 경우
    action_guide        TEXT,                               -- 치료/관리 가이드
    pre_exist_condition TEXT,                               -- 관련 기저질환 및 배경
    source_url          TEXT,                               -- 수집 원본 URL
    created_at          TIMESTAMPTZ     DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_silver_symptom_category
    ON silver_symptom(category);
CREATE INDEX IF NOT EXISTS idx_silver_symptom_red_flag
    ON silver_symptom(is_red_flag);
CREATE INDEX IF NOT EXISTS idx_silver_symptom_name
    ON silver_symptom(name);


-- =====================================================================
-- [3] silver_drug_info
-- 공공데이터 API - 의약품개요정보(e약은요)
-- DrbEasyDrugInfoService → drug_info_data.json → 이 테이블
-- 일반의약품의 효능, 사용법, 주의사항, 부작용 등 소비자 대상 정보
-- =====================================================================
CREATE TABLE IF NOT EXISTS silver_drug_info (
    drug_id             VARCHAR(20)     PRIMARY KEY,        -- 품목일련번호 (ITEM_SEQ)
    name_ko             TEXT            NOT NULL,           -- 제품명 (ITEM_NAME)
    entp_name           TEXT,                               -- 업체명 (ENTP_NAME)
    etc_otc_name        VARCHAR(50),                        -- 전문/일반 구분 (ETC_OTC_NAME)
    class_name          TEXT,                               -- 약효분류명 (CLASS_NAME)
    ingredient          TEXT,                               -- 성분/함량 (MAIN_ITEM_INGR)
    indications         TEXT,                               -- 효능·효과 (EFY_QESITM)
    dosage              TEXT,                               -- 용법·용량 (USE_METHOD_QESITM)
    warnings            TEXT,                               -- 주의사항 (ATPN_QESITM)
    interactions        TEXT,                               -- 상호작용 (INTRC_QESITM)
    side_effects        TEXT,                               -- 부작용 (SE_QESITM)
    storage_method      TEXT,                               -- 보관법 (DEPOSIT_METHOD_QESITM)
    created_at          TIMESTAMPTZ     DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_silver_drug_info_name
    ON silver_drug_info(name_ko);
CREATE INDEX IF NOT EXISTS idx_silver_drug_info_class
    ON silver_drug_info(class_name);


-- =====================================================================
-- [4] silver_taboo_info
-- 공공데이터 API - 의약품안전사용서비스(DUR) 병용금기 정보
-- DURPrdlstInfoService03 → dur_data.json → 이 테이블
-- =====================================================================
CREATE TABLE IF NOT EXISTS silver_taboo_info (
    id                  SERIAL          PRIMARY KEY,
    drug_id             VARCHAR(20)     NOT NULL,           -- 품목일련번호 (ITEM_SEQ)
    drug_name           TEXT,                               -- 품목명 (ITEM_NAME)
    mixture_drug_id     VARCHAR(20),                        -- 병용금기 대상 품목일련번호 (MIXTURE_ITEM_SEQ)
    mixture_drug_name   TEXT,                               -- 병용금기 대상 품목명 (MIXTURE_ITEM_NAME)
    mixture_ingr_code   VARCHAR(50),                        -- 병용금기 성분코드 (INGR_CODE)
    mixture_ingr_name   TEXT,                               -- 병용금기 성분명 (INGR_KOR_NAME)
    prohibited_content  TEXT,                               -- 금기 내용 (PROHBT_CONTENT)
    remark              TEXT,                               -- 비고 (REMARK)
    created_at          TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_silver_taboo_drug_id
    ON silver_taboo_info(drug_id);
CREATE INDEX IF NOT EXISTS idx_silver_taboo_mixture_drug_id
    ON silver_taboo_info(mixture_drug_id);


-- =====================================================================
-- [5] silver_drug_final
-- 공공데이터 API - 의약품 제품 허가정보
-- DrugPrdtPrmsnInfoService07 → approved_drug_data.json → 이 테이블
-- 허가 기준의 공식 효능·효과, 용법·용량, 성분 정보
-- =====================================================================
CREATE TABLE IF NOT EXISTS silver_drug_final (
    drug_id             VARCHAR(20)     PRIMARY KEY,        -- 품목일련번호 (ITEM_SEQ)
    name_ko             TEXT            NOT NULL,           -- 품목명 (ITEM_NAME)
    entp_name           TEXT,                               -- 업체명 (ENTP_NAME)
    approval_date       DATE,                               -- 품목허가일자 (ITEM_PERMIT_DATE)
    etc_otc_code        VARCHAR(10),                        -- 전문/일반 코드 (ETC_OTC_CODE)
    class_no            VARCHAR(20),                        -- 약효분류번호 (CLASS_NO)
    class_name          TEXT,                               -- 약효분류명 (CLASS_NAME)
    ingredient          TEXT,                               -- 성분/함량 (INGR_NAME)
    indications         TEXT,                               -- 효능·효과 (EFY_QESITM)
    dosage              TEXT,                               -- 용법·용량 (USE_METHOD_QESITM)
    warnings            TEXT,                               -- 주의사항 (ATPN_QESITM)
    created_at          TIMESTAMPTZ     DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_silver_drug_final_name
    ON silver_drug_final(name_ko);
CREATE INDEX IF NOT EXISTS idx_silver_drug_final_class
    ON silver_drug_final(class_no);


-- =====================================================================
-- [6] silver_drug_integration
-- silver_drug_info + silver_drug_final + silver_taboo_info 통합 뷰
-- vectorizer.py가 이 뷰에서 SELECT * 하여 청크 생성에 사용
--
-- 우선순위: silver_drug_final(허가정보) > silver_drug_info(e약은요)
--   → COALESCE로 허가정보 우선, 없으면 e약은요 데이터 사용
--   → combination_contraindication은 silver_taboo_info에서 집계
-- =====================================================================
CREATE OR REPLACE VIEW silver_drug_integration AS
SELECT
    COALESCE(f.drug_id,    i.drug_id)    AS drug_id,
    COALESCE(f.name_ko,    i.name_ko)    AS name_ko,
    COALESCE(f.entp_name,  i.entp_name)  AS entp_name,
    COALESCE(f.class_name, i.class_name) AS class_name,
    -- 성분: 허가정보 우선
    COALESCE(f.ingredient,  i.ingredient)  AS ingredient,
    -- 효능: 허가정보 우선, 없으면 e약은요
    COALESCE(f.indications, i.indications) AS indications,
    -- 용법: 허가정보 우선
    COALESCE(f.dosage,      i.dosage)      AS dosage,
    -- 주의사항: 허가정보 우선
    COALESCE(f.warnings,    i.warnings)    AS warnings,
    -- 부작용/보관법: e약은요에만 존재
    i.side_effects,
    i.storage_method,
    -- 병용금기: silver_taboo_info에서 대상 약물명 목록을 콤마 구분 문자열로 집계
    t.combination_contraindication
FROM silver_drug_final f
FULL OUTER JOIN silver_drug_info i
    ON f.drug_id = i.drug_id
LEFT JOIN (
    SELECT
        drug_id,
        STRING_AGG(
            COALESCE(mixture_drug_name, mixture_ingr_name),
            ', '
            ORDER BY mixture_drug_name
        ) AS combination_contraindication
    FROM silver_taboo_info
    GROUP BY drug_id
) t ON COALESCE(f.drug_id, i.drug_id) = t.drug_id;


-- =====================================================================
-- 확인용 쿼리
-- =====================================================================
-- SELECT table_name FROM information_schema.tables
--     WHERE table_schema = 'public' ORDER BY table_name;
--
-- SELECT COUNT(*) FROM silver_symptom;
-- SELECT COUNT(*) FROM silver_drug_info;
-- SELECT COUNT(*) FROM silver_drug_final;
-- SELECT COUNT(*) FROM silver_taboo_info;
-- SELECT COUNT(*) FROM silver_drug_integration;