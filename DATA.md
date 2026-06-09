# 데이터 설정 가이드

PostgreSQL DB 데이터를 로컬에 세팅하는 방법

---

## 사전 준비

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Git](https://git-scm.com/)
- [Python 3.8+](https://www.python.org/)
- [AWS CLI](https://aws.amazon.com/ko/cli/)

---

## 1. 레포 클론

---

## 2. DVC 설치

```bash
pip install dvc dvc-s3
```

---

## 3. AWS 인증 설정

관리자에게 **Access Key ID** 와 **Secret Access Key** 를 발급받은 후 아래 명령어 실행:

```bash
aws configure
```

입력값:

```
AWS Access Key ID:     발급받은 키 입력
AWS Secret Access Key: 발급받은 키 입력
Default region name:   ap-northeast-2
Default output format: json
```

> dvc push로 데이터 업로드

---

## 4. 데이터 다운로드

```bash
# S3에서 DB 덤프 파일 다운로드
dvc pull
```

정상적으로 완료되면 `data/dumps/` 폴더에 `.sql.gz` 파일이 생성됨

```bash
# 다운로드 확인
ls data/dumps/
```

---

## 5. 환경변수 설정

`.env.example` 을 복사해서 `.env` 파일을 만들고 실제 값을 입력.
실제 값은 관리자에게 문의.

```bash
cp .env.example .env
```

`.env` 파일 열어서 값 입력:

```env
# MinIO 설정
MINIO_ROOT_USER=관리자에게 문의
MINIO_ROOT_PASSWORD=관리자에게 문의

# PostgreSQL 설정
POSTGRES_DB=관리자에게 문의
POSTGRES_PASSWORD=관리자에게 문의
```

> ⚠️ `.env` 파일은 절대 Git에 올리면 안됨

---

## 6. DB 복원

### Docker 컨테이너 실행

```bash
docker-compose up -d
```

### 덤프 파일 복원

```bash
bash scripts/restore.sh
```

Windows 사용자는 Git Bash에서 실행

---

## 7. 연결 확인

```bash
docker exec medical_postgresql psql -U postgres -d med_db -c "\dt"
```

테이블 목록이 출력되면 정상적으로 복원

---

## 데이터 업데이트 (새 덤프가 올라왔을 때)

```bash
# 최신 포인터 파일 받기
git pull

# 최신 덤프 파일 다운로드
dvc pull

# DB 재복원
bash scripts/restore.sh
```

> `.env` 파일은 git pull로 변경되지 않으니 별도로 관리자에게 확인

---

## 폴더 구조

```
your-repo/
├── .dvc/
│   └── config                          # DVC S3 설정
├── data/
│   ├── postgresql/                     # PG 데이터 (Git 제외)
│   └── dumps/
│       └── backup_YYYYMMDD.sql.gz.dvc  # DVC 포인터 (Git 관리)
├── scripts/
│   ├── dump.sh                         # DB 덤프 스크립트 (관리자용)
│   └── restore.sh                      # DB 복원 스크립트
├── .env                                # 실제 환경변수 (Git 제외)
├── .env.example                        # 환경변수 템플릿 (Git 관리)
└── docker-compose.yml
```

---

## 문제 해결

### `dvc pull` 실패 시
AWS 인증 키가 올바른지 확인하세요.
```bash
aws s3 ls s3://agentic-rag-db-331145994962-ap-northeast-2-an
```

### DB 복원 실패 시
Docker 컨테이너가 실행 중인지 확인하세요.
```bash
docker ps
```
