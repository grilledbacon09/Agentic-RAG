# 팀원 data.zip 추출본 → Silver → ChromaDB → AI JSON
# 사전 작업: data.zip을 DE/data/ 에 압축 해제 (기존 postgres/minio/chroma 덮어쓰기 가능)

param(
    [switch]$SkipVectorize,
    [switch]$OtcOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
$env:EMBEDDING_BACKEND = if ($env:EMBEDDING_BACKEND) { $env:EMBEDDING_BACKEND } else { "simple" }
$env:VECTOR_BATCH_SIZE = if ($env:VECTOR_BATCH_SIZE) { $env:VECTOR_BATCH_SIZE } else { "32" }
if ($OtcOnly) { $env:SILVER_OTC_ONLY = "true" }

$DeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $DeRoot

$venvPython = Join-Path (Split-Path -Parent $DeRoot) "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "python" }

$csv = Join-Path $DeRoot "data\msd_source\silver_data.csv"
$drugRoot = Join-Path $DeRoot "data\minio\bronze\drug_info"

if (-not (Test-Path $csv)) {
    Write-Host "[!] $csv 가 없습니다." -ForegroundColor Red
    Write-Host "    data.zip을 DE\data\ 에 풀었는지 확인하세요." -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $drugRoot)) {
    Write-Host "[!] $drugRoot 가 없습니다." -ForegroundColor Red
    exit 1
}

Write-Host "========== Import team data -> Silver ==========" -ForegroundColor Cyan
& $venvPython src/extractor/import_team_data.py
if ($LASTEXITCODE -ne 0) {
    throw "import_team_data.py failed (exit $LASTEXITCODE)"
}

if (-not $SkipVectorize) {
    Write-Host ""
    Write-Host "========== Vectorize -> ChromaDB ==========" -ForegroundColor Cyan
    & $venvPython src/vectordb/vectorizer.py

    Write-Host ""
    Write-Host "========== Export -> AI data/*.json ==========" -ForegroundColor Cyan
    & $venvPython src/extractor/export_silver_to_ai.py

    Write-Host ""
    Write-Host "========== VectorDB test ==========" -ForegroundColor Cyan
    & $venvPython src/vectordb/test_vectordb.py "두통"
}

Write-Host ""
Write-Host "[DONE] 팀 데이터 연동 완료" -ForegroundColor Green
Write-Host "AI: cd ..\AI; ..\venv\Scripts\python.exe chat_main.py"
