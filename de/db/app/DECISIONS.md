# 회원 DB 결정 사항 정리

기준 문서: `DB_USER_SYSTEM_HANDOFF.md`. 작성: DE 파트 (2026-11-26)

- **A**: DE가 임의로 정한 것. WEB 파트에 알리고 이의가 있는지만 확인합니다.
- **B**: WEB 파트와 상의해서 정할 것. 지금은 임시값으로 넣어 두었습니다.
- **C**: handoff 6장 "DB 담당자 확인·회신 요청"에 대한 회신입니다.

---

## A. 임의로 정한 것 (알리고 이의만 확인)

| # | 정한 내용 | 이유 | 바꾸면 고칠 곳 |
|---|---|---|---|
| A1 | `app` 스키마를 약품 DB 안에 두지 않고 별도 DB `drug_app`으로 분리 | 백업·복원을 따로 하고, 팀원 계정(`drug_reader`)이 건강정보에 접근하지 못하게 하려고 | `00_bootstrap.sql` |
| A2 | 계정 2개로 분리: `app_migrator`(스키마 변경용, 동시 접속 2)와 `app_runtime`(데이터 읽기·쓰기만, 동시 접속 20) | 서버 RAM이 약 1GB라 접속 수를 제한 | `00_bootstrap.sql` |
| A3 | `app_runtime` 시간 제한: 쿼리 15초, 트랜잭션 중 대기 30초, 잠금 대기 5초 | 상담 응답을 기다리는 동안 트랜잭션을 붙잡지 않는다는 handoff 원칙에 맞춤 | `00_bootstrap.sql` |
| A4 | 비밀번호 해시가 `$argon2id$`로 시작하지 않으면 DB가 거부 | 평문 저장 사고 방지. handoff가 Argon2id를 명시해서 넣었지만, 조건 자체는 DE가 추가한 것 | V001 `users_password_hash_argon2id` |
| A5 | `email_normalized`는 소문자·앞뒤 공백 제거 형태만 허용 | handoff의 정규화 규칙을 DB에서도 검사 | V001 `users_email_normalized_form` |
| A6 | `updated_at`은 트리거가 `now()`로 덮어씀 | 백엔드가 값을 넘겨도 무시됨 | V001 트리거 |
| A7 | UUID 기본값 `gen_random_uuid()` | 백엔드가 id를 생성하는 것이 원칙이고, 넘기지 않았을 때만 쓰는 예비값 | V001 |
| A8 | `deleted_users` 테이블에 탈퇴 회원 id만 보관 (이메일 등 개인정보는 남기지 않음) | 백업 복원 후 탈퇴 회원을 다시 지우는 데 필요 | V001, `ops/reapply_deletions.sql` |
| A9 | migration은 직접 만든 `migrate.sh`(파일 체크섬 기록, 되돌리기 없음) | 회원 테이블 DROP 금지 원칙에 맞춤. 문제는 새 V 파일로 고침 | `migrate.sh` |
| A10 | 백업: 매일 한국 시간 03:30에 S3로 암호화 업로드, 서버에는 최근 3개만 보관 | — | `ops/backup.sh` |
| A11 | 회원 DB 접속은 SSL 필수, 백엔드 서버 IP만 허용 | — | `ops/EC2_SECURITY.md` |
| A12 | 복용약 `drug_id`는 약품 DB와 FK로 연결하지 않음. 저장 전에 `find_drug()`로 존재·일반의약품 여부 확인 | 약품 DB의 청크 테이블은 `item_seq`가 유일하지 않음 | README 백엔드 메모 |

---

## B. WEB 파트와 상의해서 정할 것

### 접속·환경

| # | 항목 | 지금 임시값 |
|---|---|---|
| B1 | 백엔드 서버 IP (pg_hba와 보안그룹에 넣을 값) | `<백엔드서버IP>` 빈칸 |
| B2 | 개발 환경 구성: 각자 로컬 Docker를 쓸지, EC2에 테스트용 DB를 따로 둘지 | 운영 DB 하나만 있음 |
| B3 | 백엔드 커넥션 풀 크기와 워커 수 | 풀 10 이하 권장, DB 상한 20 |
| B4 | migration 적용 시점 (백엔드 배포 전에 누가 실행할지) | DE가 실행 |

### 백엔드 구현과 맞물리는 것

| # | 항목 | 지금 임시값 |
|---|---|---|
| B5 | 비밀번호 해시 방식이 정말 Argon2id인지 (A4 조건 유지 여부) | Argon2id가 아니면 저장 거부 |
| B6 | 세션 만료 시간 | handoff 초안대로 미사용 30분 / 최대 7일. 미사용 만료는 API가 검사 |
| B7 | 처리 중 요청을 실패로 간주하는 시간 (LLM 응답이 이보다 오래 걸리면 안 됨) | 만료 후 10분 지나면 cleanup이 `failed`로 변경 |
| B8 | `drug_id`에 품목기준코드(`item_seq`)를 넣는지 | `item_seq` 9자리 가정, 길이 64자 |
| B9 | 이메일 정규화 범위 (Gmail의 점·`+` 처리 여부) | 소문자·공백 제거만 |
| B10 | 응답 본문과 `metadata` 길이 상한 | 입력 8,000자는 API에서 검사, 응답 상한은 미정 |

### 정책 (handoff 7장에서는 "서비스 담당"이 결정)

| # | 항목 | 지금 임시값 |
|---|---|---|
| B11 | 탈퇴할 때 동의 기록을 지울지 남길지 | 함께 삭제 (handoff 설계대로 CASCADE) |
| B12 | 상담 기록 보존 기간 | 무기한 (자동 삭제 없음) |
| B13 | 만료 세션과 완료된 요청 기록 보관 기간 | 세션 7일, 요청 30일 |
| B14 | 백업 보관 기간 | S3에서 30일 (버킷 설정 필요) |
| B15 | 이메일 인증을 할지 | 컬럼(`email_verified_at`)만 있고 사용 여부 미정 |
| B16 | 나이 수집 방식 (정확한 나이인지, 기존 "20대" 같은 값은 어떻게 할지) | 정확한 나이 0~120 |
| B17 | 같은 버전 약관에 다시 동의할 때 처리 | handoff 초안대로 `accepted_at`을 갱신하고 `withdrawn_at`을 비움 |
| B18 | 기존 `user_01`·익명 사용자 데이터 | 이관하지 않고 빈 테이블에서 시작 |

---

## C. handoff 6장 회신

| 질문 | 회신 |
|---|---|
| PG 버전, DB명, 기존 회원 테이블 | PostgreSQL 15, 새 DB `drug_app`, 기존 회원 테이블 없음 |
| 스키마를 추가할지 DB를 따로 둘지 | DB를 따로 두고 그 안에 `app` 스키마 (A1) |
| 환경, 접속·TLS | EC2 `43.200.194.39:5433`, SSL 필수. 개발 환경은 B2 |
| 계정 분리 | `app_migrator`와 `app_runtime`으로 분리 완료. 비밀번호는 개별 전달 (DE 파트에 문의) |
| 제품 마스터 | PG에는 없고 Neo4j의 `Drug.item_seq`(42,746개)가 유일한 제품 목록이라 FK 대신 API에서 확인 |
| migration 도구·담당·일정 | `migrate.sh`, DE가 실행. 일정은 B4 |
| 연결 한도, 백업·정리 담당 | 동시 접속 20, 매일 S3 백업과 정리 작업 모두 DE 담당 |
| 보존·탈퇴 정책 | B11~B18 회의에서 확정 |

---

## 우선순위

가장 먼저 받아야 할 것은 **B1(백엔드 IP)**입니다. 이 값이 있어야 EC2 보안 설정과 회원 DB 적용을 시작할 수 있습니다. 나머지 B 항목은 지금 임시값으로도 동작합니다. 정해지면 대부분 `ops/cleanup.sql`의 숫자나 새 V 파일 하나로 고칠 수 있습니다.

---

## D. WEB 회신 반영 결과 (2026-11-27)

WEB 회신(`REPLY.md`)과 DE 결정을 V001에 반영했습니다. EC2 적용 전이라 V002를 만들지 않고 V001을 직접 고쳤습니다.

| # | 최종 | 반영 위치 |
|---|---|---|
| B1 | 백엔드 IP는 WEB이 확정 후 전달 (대기) | `ops/EC2_SECURITY.md` 4단계 |
| B2 | 테스트 DB `drug_app_test` + 계정 `app_test_migrator`·`app_test_runtime` 신설. 테스트 접속 IP: hj `211.33.76.53` | `00_bootstrap.sql`, `ops/EC2_SECURITY.md` |
| B3 | 워커 1 × 연결 4 → 접속 상한 운영 8, 테스트 5 | `00_bootstrap.sql` |
| B4 | DE가 실행. 테스트 DB 먼저, 운영은 B1 받은 뒤 | `README.md` 적용 순서 |
| B5 | Argon2id, A4 유지 | 변경 없음 |
| B6 | 미사용 30분 / 절대 7일 유지 | `ops/cleanup.sql` 기산점에 반영 |
| B7 | DE 제안값 확정: LLM 타임아웃 90초, 최초 lease 120초, 갱신 없음. 1차 회수는 API(다음 요청 시 즉시), 2차는 cron(만료 10분 후, 10분마다) | `ops/reclaim_leases.sql` |
| B8 | `drug_id` NOT NULL, 숫자 9자리, `(user_id, drug_id)` UNIQUE. `name_normalized`·이름 기반 UNIQUE 삭제. `name`은 표시용 스냅샷으로 유지. **전문의약품 저장 허용** (A12 변경: 존재 확인만, 일반의약품 제한은 추천에만) | V001 `user_medications` |
| B9 | **DE 결정: 전체 소문자화 유지 (a안).** WEB 회신의 대소문자 구분안은 채택하지 않음. 제약을 `email_normalized = lower(btrim(email))`로 강화 | V001 `users` |
| B10 | 본문 8,000자: API 검사 + DB 안전장치(`char_length`). metadata 8,000자는 API에서만 | V001 `chat_messages` |
| B11 | 동의 기록 CASCADE 삭제 유지 | 변경 없음 |
| B12 | 상담 무기한 보존 | 변경 없음 |
| B13 | 세션: 실제 종료 시각 + 7일. 요청: `finished_at` + 30일, 메시지 참조 요청은 상담 삭제까지 보존, processing 제외 | V001 `finished_at`, `ops/cleanup.sql` |
| B14 | S3 30일 (버킷 수명주기 규칙 설정 필요) | 콘솔 작업 |
| B15 | 이메일 인증 미구현, `email_verified_at` NULL 유지 | 변경 없음 |
| B16 | 정확한 나이 0~120 유지 | 변경 없음 |
| B17 | 재동의 초안 유지 | 변경 없음 |
| B18 | 빈 테이블에서 시작 | 변경 없음 |
