# 팀 data.zip 기반 전체 데이터셋 구축 (Silver + Chroma + AI JSON)
#
# 사전:
#   1. Docker Desktop 실행
#   2. database/data/ 에 msd_source + minio (drug_info, taboo_info) 배치
#
# 실행:
#   cd database
#   .\run_full_dataset.ps1

param(
    [switch]$SkipTaboo,
    [switch]$SkipVectorize,
    [switch]$OtcOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
$env:EMBEDDING_BACKEND = if ($env:EMBEDDING_BACKEND) { $env:EMBEDDING_BACKEND } else { "simple" }
$env:VECTOR_BATCH_SIZE = if ($env:VECTOR_BATCH_SIZE) { $env:VECTOR_BATCH_SIZE } else { "32" }
if ($SkipTaboo) { $env:SKIP_TABOO = "true" }
if ($OtcOnly) { $env:SILVER_OTC_ONLY = "true" }

$DeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $DeRoot

$venvPython = Join-Path (Split-Path -Parent $DeRoot) "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "python" }

Write-Host "========== Preflight ==========" -ForegroundColor Cyan
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Docker Desktop이 실행 중이 아닙니다." -ForegroundColor Red
    Write-Host "    Docker Desktop을 켠 뒤 다시 실행하세요." -ForegroundColor Yellow
    exit 1
}

Write-Host "========== Docker compose up ==========" -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

Write-Host "========== PostgreSQL DDL ==========" -ForegroundColor Cyan
Start-Sleep -Seconds 4
Get-Content "src\infra\init_postresql.sql" | docker exec -i medical_postgresql psql -U postgres -d med_db
if ($LASTEXITCODE -ne 0) { throw "init_postresql.sql failed" }

Write-Host "========== Import team data -> Silver ==========" -ForegroundColor Cyan
& $venvPython src/extractor/import_team_data.py
if ($LASTEXITCODE -ne 0) { throw "import_team_data.py failed" }

if (-not $SkipVectorize) {
    Write-Host ""
    Write-Host "========== Vectorize -> ChromaDB ==========" -ForegroundColor Cyan
    & $venvPython src/vectordb/vectorizer.py
    if ($LASTEXITCODE -ne 0) { throw "vectorizer.py failed" }

    Write-Host ""
    Write-Host "========== Export -> ../data/*.json ==========" -ForegroundColor Cyan
    & $venvPython src/extractor/export_silver_to_ai.py
    if ($LASTEXITCODE -ne 0) { throw "export_silver_to_ai.py failed" }

    Write-Host ""
    Write-Host "========== VectorDB test ==========" -ForegroundColor Cyan
    & $venvPython src/vectordb/test_vectordb.py "두통"
}

Write-Host ""
Write-Host "========== Summary ==========" -ForegroundColor Cyan
docker exec medical_postgresql psql -U postgres -d med_db -c "SELECT COUNT(*) AS symptom FROM silver_symptom; SELECT COUNT(*) AS drug FROM silver_drug_info; SELECT COUNT(*) AS taboo FROM silver_taboo_info;"
& $venvPython -c "import json; from pathlib import Path; r=Path('..')/'data'; d=json.load(open(r/'drugs.json',encoding='utf-8')); s=json.load(open(r/'symptoms.json',encoding='utf-8')); print(f'AI JSON: drugs={len(d)}, symptoms={len(s)}')"

Write-Host ""
Write-Host "[DONE] 전체 데이터셋 구축 완료" -ForegroundColor Green
Write-Host "채팅 테스트: cd ..\agents; ..\venv\Scripts\python.exe chat_main.py"
