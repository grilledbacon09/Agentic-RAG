# DE 전체 데이터 파이프라인 (샘플 → 실데이터)
# 사용법:
#   .\run_full_pipeline.ps1              # 전체 실행
#   .\run_full_pipeline.ps1 -Step ingest # 단계별 실행
#
# 단계: preflight | ingest | silver | msd | vectorize | export | test

param(
    [ValidateSet("all", "preflight", "ingest", "silver", "msd", "vectorize", "export", "test")]
    [string]$Step = "all",
    [string]$Query = "두통"
)

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
$env:EMBEDDING_BACKEND = if ($env:EMBEDDING_BACKEND) { $env:EMBEDDING_BACKEND } else { "simple" }
$env:VECTOR_BATCH_SIZE = if ($env:VECTOR_BATCH_SIZE) { $env:VECTOR_BATCH_SIZE } else { "32" }

$DeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $DeRoot

$venvPython = Join-Path (Split-Path -Parent $DeRoot) "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "python"
}

function Invoke-Step([string]$Name, [string]$Script) {
    Write-Host ""
    Write-Host "========== $Name ==========" -ForegroundColor Cyan
    & $venvPython $Script
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Step failed: $Name (exit $LASTEXITCODE)"
    }
}

function Step-MsdIfReady() {
    $msdHtml = Join-Path $DeRoot "data\msd_source\symptoms.html"
    $linksCsv = Join-Path $DeRoot "data\msd_source\links.csv"
    if (Test-Path $msdHtml) {
        Invoke-Step "MSD link collect" "src/collector/msd_link_collector.py"
    }
    if (Test-Path $linksCsv) {
        Invoke-Step "MSD save to silver" "src/extractor/msd_save_to_silver.py"
    } else {
        Write-Host "[*] MSD 증상 수집 스킵 (symptoms.html / links.csv 없음)" -ForegroundColor Yellow
    }
}

switch ($Step) {
    "preflight" { Invoke-Step "Preflight" "src/pipeline/preflight.py" }
    "ingest"    { Invoke-Step "API ingest (Bronze)" "src/collector/api_ingestion.py" }
    "silver"    { Invoke-Step "Bronze -> Silver" "src/extractor/api_save_to_silver.py" }
    "msd"       { Step-MsdIfReady }
    "vectorize" { Invoke-Step "Vectorize -> ChromaDB" "src/vectordb/vectorizer.py" }
    "export"    { Invoke-Step "Export Silver -> AI JSON" "src/extractor/export_silver_to_ai.py" }
    "test"      { Invoke-Step "VectorDB test" "src/vectordb/test_vectordb.py $Query" }
    "all" {
        Invoke-Step "Preflight" "src/pipeline/preflight.py"
        Invoke-Step "API ingest (Bronze)" "src/collector/api_ingestion.py"
        Invoke-Step "Bronze -> Silver" "src/extractor/api_save_to_silver.py"
        Step-MsdIfReady
        Invoke-Step "Vectorize -> ChromaDB" "src/vectordb/vectorizer.py"
        Invoke-Step "Export Silver -> AI JSON" "src/extractor/export_silver_to_ai.py"
        Invoke-Step "VectorDB test" "src/vectordb/test_vectordb.py $Query"
        Write-Host ""
        Write-Host "[DONE] 전체 파이프라인 완료" -ForegroundColor Green
        Write-Host "AI 채팅: cd ..\AI; ..\venv\Scripts\python.exe chat_main.py"
    }
}
