param([string]$Python = "")
$ErrorActionPreference = 'Stop'
if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }
$taskVenv = Join-Path $PSScriptRoot '.venv'
$taskPython = Join-Path $taskVenv 'Scripts\python.exe'
$taskEnv = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path -LiteralPath $taskEnv)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination $taskEnv
}
if (-not (Test-Path -LiteralPath $taskPython)) {
    & $Python -m venv $taskVenv
    if ($LASTEXITCODE -ne 0) { throw 'Python 가상환경 생성에 실패했습니다.' }
}
& $taskPython -m pip install -r (Join-Path $PSScriptRoot 'backend\module2\requirements.txt') --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw '패키지 설치에 실패했습니다. 네트워크 연결을 확인하고 setup.ps1을 다시 실행하세요.' }
Write-Host '설치 완료. .env에 ANTHROPIC_API_KEY를 입력하고 .\start_demo.ps1을 실행하세요.'
