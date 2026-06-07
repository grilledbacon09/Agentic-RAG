# DE 파트 실행 헬퍼 (PowerShell)
# 사용법: .\run.ps1 seed | vectorize | test [query]

param(
    [Parameter(Position = 0)]
    [ValidateSet("seed", "import", "json", "vectorize", "export", "test", "full")]
    [string]$Step = "seed",
    [string]$Query = "두통"
)

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
$DeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $DeRoot

$venvPython = Join-Path (Split-Path -Parent $DeRoot) "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "python"
}

switch ($Step) {
    "install-embed" {
        & (Join-Path (Split-Path -Parent $DeRoot) "venv\Scripts\pip.exe") install sentence-transformers
    }
    "seed" {
        & $venvPython src/extractor/seed_dev_data.py
    }
    "import" {
        & (Join-Path $DeRoot "run_import_team_data.ps1")
    }
    "json" {
        & (Join-Path $DeRoot "run_export_no_docker.ps1")
    }
    "vectorize" {
        & $venvPython src/vectordb/vectorizer.py
    }
    "export" {
        & $venvPython src/extractor/export_silver_to_ai.py
    }
    "test" {
        & $venvPython src/vectordb/test_vectordb.py $Query
    }
    "full" {
        & (Join-Path $DeRoot "run_full_pipeline.ps1")
    }
}
