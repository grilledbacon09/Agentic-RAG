# Docker 없이 팀 data → AI JSON (PostgreSQL/Chroma 불필요)
#
# 사전: database/data/msd_source + minio/bronze (drug_info, taboo_info)
#
# 실행:
#   cd database
#   .\run_export_no_docker.ps1

param(
    [switch]$SkipTaboo,
    [switch]$OtcOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
if ($SkipTaboo) { $env:SKIP_TABOO = "true" }
if ($OtcOnly) { $env:SILVER_OTC_ONLY = "true" }

$DeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $DeRoot

$venvPython = Join-Path (Split-Path -Parent $DeRoot) "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "python" }

Write-Host "========== Export team data -> JSON (no Docker) ==========" -ForegroundColor Cyan
& $venvPython src/extractor/export_team_data_direct.py
if ($LASTEXITCODE -ne 0) { throw "export failed" }

Write-Host ""
& $venvPython -c "import json; from pathlib import Path; r=Path('..')/'data'; d=json.load(open(r/'drugs.json',encoding='utf-8')); s=json.load(open(r/'symptoms.json',encoding='utf-8')); c=sum(1 for x in d if x.get('combination_contraindication')); print(f'drugs={len(d)}, symptoms={len(s)}, with_contra={c}')"

Write-Host ""
Write-Host "[DONE] 루트 data/*.json 갱신됨" -ForegroundColor Green
Write-Host "채팅: cd ..\agents; `$env:USE_CHROMA='false'; ..\venv\Scripts\python.exe chat_main.py"
