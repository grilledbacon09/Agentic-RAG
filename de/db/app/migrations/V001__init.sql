-- ============================================================
-- V001__init.sql — 회원 기능 초기 스키마 (app 스키마, 9개 테이블 + 운영 테이블 2개)
-- ============================================================
-- 실행 계정: app_migrator (app 스키마 소유자). 실행기: db/app/migrate.sh
-- 기준: DB_USER_SYSTEM_HANDOFF.md 3장 설계안 + DB 담당 보강
--   보강 1. 정규화 컬럼을 DB에서도 강제 (email_normalized = lower(btrim(...)))
--   보강 2. UUID PK 예비 기본값 gen_random_uuid() (백엔드가 넘기면 그 값 사용)
--   보강 3. updated_at 자동 갱신 트리거 (백엔드가 넘겨도 now()로 맞춤)
--   보강 4. 운영 테이블: schema_migrations(적용 기록), deleted_users(백업 복원 후 탈퇴 재삭제용)
--   보강 5. FK 자식 쪽 인덱스 (user_medications.user_id)
-- WEB 회신(REPLY.md) 반영 — 2026-11-27, EC2 적용 전이라 V001에 직접 반영
--   B8  복용약은 검색 결과 선택만 → drug_id(item_seq 9자리) 필수, 회원별 UNIQUE, name_normalized 제거
--       전문의약품도 저장 허용 (병용금기 검사에 필요). 존재 확인은 API에서 find_drug(otc_only=False)
--   B9  이메일은 소문자화 유지 (DE 결정 a). email_normalized = lower(btrim(email))
--   B10 메시지 본문 8,000자 (char_length = 코드 포인트 수). metadata 상한은 API에서만 검사
--   B13 chat_requests.finished_at: 완료·실패 시각. 보관 기간(30일)은 updated_at이 아닌 이 값 기준
-- 실행 변수: runtime_role (migrate.sh가 넘김. 운영 app_runtime / 테스트 app_test_runtime)
-- 모든 시각은 timestamptz (계정 timezone = UTC)
-- ============================================================

SET search_path = app;

-- ── 공통: updated_at 자동 갱신 ──────────────────────────────
CREATE FUNCTION app.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- ── 3.1 users: 회원 계정 ────────────────────────────────────
CREATE TABLE app.users (
    id                uuid         NOT NULL DEFAULT gen_random_uuid(),
    email             varchar(254) NOT NULL,
    email_normalized  varchar(254) NOT NULL,
    password_hash     text         NOT NULL,
    status            varchar(20)  NOT NULL DEFAULT 'active',
    email_verified_at timestamptz,
    created_at        timestamptz  NOT NULL DEFAULT now(),
    updated_at        timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT users_pkey PRIMARY KEY (id),
    CONSTRAINT users_email_normalized_key UNIQUE (email_normalized),
    CONSTRAINT users_email_not_blank CHECK (btrim(email) <> ''),
    CONSTRAINT users_email_normalized_form CHECK (email_normalized <> '' AND email_normalized = lower(btrim(email))),
    CONSTRAINT users_password_hash_argon2id CHECK (password_hash LIKE '$argon2id$%'),
    CONSTRAINT users_status_check CHECK (status IN ('active', 'disabled'))
);
COMMENT ON TABLE app.users IS '회원 계정. 이메일 검증·Argon2id 해싱은 백엔드에서 수행';
COMMENT ON COLUMN app.users.email_normalized IS 'lower(btrim(email)). 가입 중복 검사·로그인 조회는 이 값으로. 점·플러스는 제거하지 않음';

-- ── 3.2 user_profiles: 건강설정 ─────────────────────────────
CREATE TABLE app.user_profiles (
    user_id           uuid        NOT NULL,
    gender            varchar(20) NOT NULL DEFAULT 'unspecified',
    age               smallint,
    age_recorded_at   timestamptz,
    allergy_status    varchar(10) NOT NULL DEFAULT 'unknown',
    medication_status varchar(10) NOT NULL DEFAULT 'unknown',
    version           bigint      NOT NULL DEFAULT 1,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_profiles_pkey PRIMARY KEY (user_id),
    CONSTRAINT user_profiles_user_fk FOREIGN KEY (user_id) REFERENCES app.users (id) ON DELETE CASCADE,
    CONSTRAINT user_profiles_gender_check CHECK (gender IN ('male', 'female', 'other', 'unspecified')),
    CONSTRAINT user_profiles_age_range CHECK (age IS NULL OR age BETWEEN 0 AND 120),
    CONSTRAINT user_profiles_age_pair CHECK ((age IS NULL) = (age_recorded_at IS NULL)),
    CONSTRAINT user_profiles_allergy_status_check CHECK (allergy_status IN ('unknown', 'none', 'known')),
    CONSTRAINT user_profiles_medication_status_check CHECK (medication_status IN ('unknown', 'none', 'known')),
    CONSTRAINT user_profiles_version_positive CHECK (version > 0)
);
COMMENT ON COLUMN app.user_profiles.version IS '동시 수정 충돌 검사용 (UPDATE ... WHERE version = :old → version + 1)';

-- ── 3.3 user_allergies: 알레르기 목록 ───────────────────────
CREATE TABLE app.user_allergies (
    id              uuid         NOT NULL DEFAULT gen_random_uuid(),
    user_id         uuid         NOT NULL,
    name            varchar(200) NOT NULL,
    name_normalized varchar(200) NOT NULL,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT user_allergies_pkey PRIMARY KEY (id),
    CONSTRAINT user_allergies_user_fk FOREIGN KEY (user_id) REFERENCES app.users (id) ON DELETE CASCADE,
    CONSTRAINT user_allergies_user_name_key UNIQUE (user_id, name_normalized),
    CONSTRAINT user_allergies_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT user_allergies_name_normalized_not_blank CHECK (btrim(name_normalized) <> '')
);

-- ── 3.4 user_medications: 복용약 목록 ───────────────────────
CREATE TABLE app.user_medications (
    id         uuid         NOT NULL DEFAULT gen_random_uuid(),
    user_id    uuid         NOT NULL,
    drug_id    varchar(64)  NOT NULL,
    name       varchar(300) NOT NULL,
    created_at timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT user_medications_pkey PRIMARY KEY (id),
    CONSTRAINT user_medications_user_fk FOREIGN KEY (user_id) REFERENCES app.users (id) ON DELETE CASCADE,
    CONSTRAINT user_medications_user_drug_key UNIQUE (user_id, drug_id),
    CONSTRAINT user_medications_drug_id_item_seq CHECK (drug_id ~ '^[0-9]{9}$'),
    CONSTRAINT user_medications_name_not_blank CHECK (btrim(name) <> '')
);
-- (user_id, drug_id) UNIQUE 인덱스가 user_id 조회도 처리하므로 별도 user_id 인덱스 없음
COMMENT ON COLUMN app.user_medications.drug_id IS
    '품목기준코드 item_seq(숫자 9자리)만 저장. 이름·바코드·AI 내부 ID 금지. 약품 DB에 제품 마스터 테이블이 없어 FK 없음 → API에서 find_drug(otc_only=False)로 확인. 전문의약품 허용';
COMMENT ON COLUMN app.user_medications.name IS '추가 시점 제품명 스냅샷 (화면 표시용. 그래프에서 제품이 빠지거나 이름이 바뀌어도 목록 유지)';

-- ── 3.5 auth_sessions: 로그인 세션 ──────────────────────────
CREATE TABLE app.auth_sessions (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    user_id         uuid        NOT NULL,
    token_hash      char(64)    NOT NULL,
    csrf_token_hash char(64)    NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    CONSTRAINT auth_sessions_pkey PRIMARY KEY (id),
    CONSTRAINT auth_sessions_user_fk FOREIGN KEY (user_id) REFERENCES app.users (id) ON DELETE CASCADE,
    CONSTRAINT auth_sessions_token_hash_key UNIQUE (token_hash),
    CONSTRAINT auth_sessions_token_hash_hex CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT auth_sessions_csrf_hash_hex CHECK (csrf_token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT auth_sessions_expires_after_created CHECK (expires_at > created_at),
    CONSTRAINT auth_sessions_seen_after_created CHECK (last_seen_at >= created_at),
    CONSTRAINT auth_sessions_revoked_after_created CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX auth_sessions_user_idx ON app.auth_sessions (user_id);
CREATE INDEX auth_sessions_expires_idx ON app.auth_sessions (expires_at);
COMMENT ON TABLE app.auth_sessions IS '원문 토큰은 저장하지 않음. 만료 초안 idle 30분(last_seen_at, API 검사) / absolute 7일';

-- ── 3.6 user_consents: 동의 기록 ────────────────────────────
CREATE TABLE app.user_consents (
    id             uuid        NOT NULL DEFAULT gen_random_uuid(),
    user_id        uuid        NOT NULL,
    consent_type   varchar(40) NOT NULL,
    policy_version varchar(40) NOT NULL,
    accepted_at    timestamptz NOT NULL,
    withdrawn_at   timestamptz,
    CONSTRAINT user_consents_pkey PRIMARY KEY (id),
    CONSTRAINT user_consents_user_fk FOREIGN KEY (user_id) REFERENCES app.users (id) ON DELETE CASCADE,
    CONSTRAINT user_consents_user_type_version_key UNIQUE (user_id, consent_type, policy_version),
    CONSTRAINT user_consents_type_check CHECK (consent_type IN ('terms', 'privacy', 'health_data')),
    CONSTRAINT user_consents_version_not_blank CHECK (btrim(policy_version) <> ''),
    CONSTRAINT user_consents_withdrawn_after_accepted CHECK (withdrawn_at IS NULL OR withdrawn_at >= accepted_at)
);

-- ── 3.7 chats: 상담방 및 엔진 상태 ──────────────────────────
CREATE TABLE app.chats (
    id                   uuid         NOT NULL DEFAULT gen_random_uuid(),
    user_id              uuid         NOT NULL,
    title                varchar(200) NOT NULL DEFAULT '새 상담',
    profile_version      bigint,
    profile_snapshot     jsonb        NOT NULL DEFAULT '{}'::jsonb,
    session_state        jsonb        NOT NULL,
    state_schema_version integer      NOT NULL DEFAULT 1,
    revision             bigint       NOT NULL DEFAULT 0,
    next_sequence        bigint       NOT NULL DEFAULT 1,
    created_at           timestamptz  NOT NULL DEFAULT now(),
    updated_at           timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT chats_pkey PRIMARY KEY (id),
    CONSTRAINT chats_user_fk FOREIGN KEY (user_id) REFERENCES app.users (id) ON DELETE CASCADE,
    CONSTRAINT chats_title_not_blank CHECK (btrim(title) <> ''),
    CONSTRAINT chats_profile_version_positive CHECK (profile_version IS NULL OR profile_version > 0),
    CONSTRAINT chats_profile_snapshot_object CHECK (jsonb_typeof(profile_snapshot) = 'object'),
    CONSTRAINT chats_session_state_object CHECK (jsonb_typeof(session_state) = 'object'),
    CONSTRAINT chats_state_schema_version_check CHECK (state_schema_version >= 1),
    CONSTRAINT chats_revision_check CHECK (revision >= 0),
    CONSTRAINT chats_next_sequence_check CHECK (next_sequence >= 1)
);
CREATE INDEX chats_user_updated_idx ON app.chats (user_id, updated_at DESC, id);

-- ── 3.8 chat_requests: 상담 요청·중복 방지 ──────────────────
CREATE TABLE app.chat_requests (
    id                uuid        NOT NULL DEFAULT gen_random_uuid(),
    chat_id           uuid        NOT NULL,
    client_request_id uuid        NOT NULL,
    payload_hash      char(64)    NOT NULL,
    status            varchar(16) NOT NULL DEFAULT 'processing',
    lease_token       uuid,
    lease_expires_at  timestamptz,
    finished_at       timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chat_requests_pkey PRIMARY KEY (id),
    CONSTRAINT chat_requests_chat_fk FOREIGN KEY (chat_id) REFERENCES app.chats (id) ON DELETE CASCADE,
    CONSTRAINT chat_requests_chat_client_key UNIQUE (chat_id, client_request_id),
    CONSTRAINT chat_requests_id_chat_key UNIQUE (id, chat_id),
    CONSTRAINT chat_requests_payload_hash_hex CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chat_requests_status_check CHECK (status IN ('processing', 'completed', 'failed')),
    CONSTRAINT chat_requests_lease_matches_status CHECK (
        (status = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)),
    CONSTRAINT chat_requests_finished_matches_status CHECK ((status = 'processing') = (finished_at IS NULL)),
    CONSTRAINT chat_requests_finished_after_created CHECK (finished_at IS NULL OR finished_at >= created_at)
);
COMMENT ON COLUMN app.chat_requests.finished_at IS
    'completed/failed로 바뀐 시각 (트리거가 기록, processing으로 돌아가면 NULL). 보관 30일의 기산점';
CREATE UNIQUE INDEX chat_requests_one_processing_per_chat
    ON app.chat_requests (chat_id) WHERE status = 'processing';

-- ── 3.9 chat_messages: 상담 메시지 ──────────────────────────
CREATE TABLE app.chat_messages (
    id         uuid        NOT NULL DEFAULT gen_random_uuid(),
    chat_id    uuid        NOT NULL,
    request_id uuid,
    sequence   bigint      NOT NULL,
    role       varchar(16) NOT NULL,
    content    text        NOT NULL,
    metadata   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chat_messages_pkey PRIMARY KEY (id),
    CONSTRAINT chat_messages_chat_fk FOREIGN KEY (chat_id) REFERENCES app.chats (id) ON DELETE CASCADE,
    CONSTRAINT chat_messages_request_fk FOREIGN KEY (request_id, chat_id)
        REFERENCES app.chat_requests (id, chat_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT chat_messages_chat_sequence_key UNIQUE (chat_id, sequence),
    CONSTRAINT chat_messages_sequence_positive CHECK (sequence > 0),
    CONSTRAINT chat_messages_role_check CHECK (role IN ('user', 'assistant', 'system')),
    CONSTRAINT chat_messages_content_length CHECK (char_length(content) <= 8000),
    CONSTRAINT chat_messages_metadata_object CHECK (jsonb_typeof(metadata) = 'object')
);
CREATE INDEX chat_messages_request_idx ON app.chat_messages (request_id, chat_id);
COMMENT ON TABLE app.chat_messages IS '저장 후 불변 (updated_at 없음). 본문 8,000자는 API가 먼저 검사하고 DB는 안전장치. 잘라서 저장하지 않음';

-- ── updated_at 트리거 ───────────────────────────────────────
CREATE TRIGGER users_touch_updated_at BEFORE UPDATE ON app.users
    FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
CREATE TRIGGER user_profiles_touch_updated_at BEFORE UPDATE ON app.user_profiles
    FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
CREATE TRIGGER chats_touch_updated_at BEFORE UPDATE ON app.chats
    FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
CREATE TRIGGER chat_requests_touch_updated_at BEFORE UPDATE ON app.chat_requests
    FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();

-- 요청 종료 시각: 상태가 바뀔 때만 기록 (다른 컬럼 수정으로 기산점이 바뀌지 않음)
CREATE FUNCTION app.set_request_finished_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'processing' THEN
        NEW.finished_at := NULL;
    ELSIF TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status THEN
        NEW.finished_at := now();
    ELSE
        NEW.finished_at := OLD.finished_at;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER chat_requests_set_finished_at BEFORE INSERT OR UPDATE ON app.chat_requests
    FOR EACH ROW EXECUTE FUNCTION app.set_request_finished_at();

-- ── 운영: 탈퇴 기록 (백업 복원 후 재삭제용) ─────────────────
-- 탈퇴 트랜잭션에서 users 삭제와 함께 INSERT. 이메일 등 개인정보는 남기지 않고 id만 보관
CREATE TABLE app.deleted_users (
    user_id    uuid        NOT NULL,
    deleted_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT deleted_users_pkey PRIMARY KEY (user_id)
);
COMMENT ON TABLE app.deleted_users IS '백업 복원 후 ops/reapply_deletions.sql로 탈퇴 회원을 다시 삭제하기 위한 id 목록';

-- ── 권한: 백엔드 계정(runtime_role)은 필요한 CRUD만 ───────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON
    app.users, app.user_profiles, app.user_allergies, app.user_medications,
    app.auth_sessions, app.user_consents, app.chats, app.chat_requests, app.chat_messages
TO :"runtime_role";
GRANT SELECT, INSERT ON app.deleted_users TO :"runtime_role";
-- 이후 migration에서 만드는 테이블은 각 migration에서 명시적으로 GRANT (자동 부여 안 함)
