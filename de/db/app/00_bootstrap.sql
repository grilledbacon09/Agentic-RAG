-- ============================================================
-- 00_bootstrap.sql — 회원 DB와 계정 만들기 (superuser로 1회, 다시 실행해도 안전)
-- ============================================================
-- 같은 파일로 운영 DB와 테스트 DB를 만듭니다. 이름·접속 상한은 변수로 넘깁니다.
--
-- 운영 (EC2 서버 안에서):
--   sudo -u postgres psql -p 5433 -v ON_ERROR_STOP=1 \
--     -v db=drug_app -v migrator=app_migrator -v runtime=app_runtime -v runtime_limit=8 \
--     -v migrator_pw='<비밀번호>' -v runtime_pw='<비밀번호>' -f 00_bootstrap.sql
-- 테스트 (WEB 개발용, 운영과 계정·비밀번호 분리):
--   sudo -u postgres psql -p 5433 -v ON_ERROR_STOP=1 \
--     -v db=drug_app_test -v migrator=app_test_migrator -v runtime=app_test_runtime -v runtime_limit=5 \
--     -v migrator_pw='<비밀번호>' -v runtime_pw='<비밀번호>' -f 00_bootstrap.sql
-- 로컬 Docker: docker exec -i drug_rag_postgres psql -U airflow -d postgres -v ON_ERROR_STOP=1 -v db=drug_app ... < 00_bootstrap.sql
--
-- 비밀번호는 이 파일·Git·노션에 적지 않고 실행할 때만 넘깁니다.
-- 약품 DB(drug_rag)와 분리한 이유: 회원 데이터는 다시 만들 수 없어 백업·복원을 따로 하고,
-- 팀원용 drug_reader 계정이 건강정보에 접근하지 못하게 하기 위해서입니다.
-- 접속 상한: WEB 초기 구성은 워커 1개 × 연결 4개 (B3). 운영 8 = 4 + 재배포 때 겹치는 여유
-- ============================================================

SET password_encryption = 'scram-sha-256';

-- ── 계정 ────────────────────────────────────────────────────
-- migrator: app 스키마의 소유자. 스키마 생성·변경(migration)만 사용
-- runtime : 백엔드가 쓰는 계정. 테이블 CRUD만 (DDL 불가)
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'migrator', :'migrator_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migrator') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'runtime', :'runtime_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'runtime') \gexec

ALTER ROLE :"migrator" NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
ALTER ROLE :"runtime"  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT :runtime_limit;

-- ── DB ──────────────────────────────────────────────────────
SELECT format('CREATE DATABASE %I ENCODING ''UTF8'' TEMPLATE template0', :'db')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec

-- 기본 PUBLIC 권한 제거 → 명시적으로 허용한 계정만 접속
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO :"migrator";
GRANT CONNECT ON DATABASE :"db" TO :"runtime";

-- 약품 DB 쪽 계정은 회원 DB에 접근 불가 (PUBLIC 회수로 이미 막혔지만 명시)
SELECT format('REVOKE ALL ON DATABASE %I FROM drug_reader', :'db')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'drug_reader') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM airflow', :'db')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'airflow' AND NOT rolsuper) \gexec

-- 계정 기본 설정: 스키마 경로, UTC, 오래 붙잡는 트랜잭션 방지
ALTER ROLE :"runtime"  IN DATABASE :"db" SET search_path = app;
ALTER ROLE :"migrator" IN DATABASE :"db" SET search_path = app;
ALTER ROLE :"runtime"  IN DATABASE :"db" SET timezone = 'UTC';
ALTER ROLE :"migrator" IN DATABASE :"db" SET timezone = 'UTC';
ALTER ROLE :"runtime"  IN DATABASE :"db" SET statement_timeout = '15s';
ALTER ROLE :"runtime"  IN DATABASE :"db" SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE :"runtime"  IN DATABASE :"db" SET lock_timeout = '5s';

-- ── 스키마 (회원 DB 안에서) ─────────────────────────────────
\connect :db
REVOKE ALL ON SCHEMA public FROM PUBLIC;
SELECT format('CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION %I', :'migrator') \gexec
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA app TO :"runtime";

-- 확인
SELECT rolname, rolconnlimit, rolcanlogin FROM pg_roles WHERE rolname IN (:'migrator', :'runtime');
SELECT current_database() AS db, nspname, pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname = 'app';
