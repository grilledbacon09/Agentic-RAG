# AI 파트 실행 헬퍼 (PowerShell)
# 사용법: .\run.ps1 basic | enhanced

param(
    [Parameter(Position = 0)]
    [ValidateSet("basic", "enhanced", "chat", "web", "chroma-test")]
    [string]$Mode = "web"
)

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
$AiRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $AiRoot
Set-Location $AiRoot

$venvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "python"
}

switch ($Mode) {
    "basic" {
        & $venvPython main.py
    }
    "enhanced" {
        & $venvPython enhanced_main.py
    }
    "chat" {
        & $venvPython chat_main.py
    }
    "web" {
        & (Join-Path $ProjectRoot "venv\Scripts\pip.exe") install gradio -q
        & $venvPython chat_web.py
    }
    "chroma-test" {
        & $venvPython chroma_retriever.py 두통
    }
}
