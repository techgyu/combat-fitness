param(
    [string]$Python = "",
    [int]$Port = 8000,
    [Alias("MockPort")][int]$Module2Port = 8001,
    [string]$Module2Url = "",
    [switch]$MockModule2,
    [switch]$OpenBrowser
)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $taskVenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $taskVenvPython) { $Python = $taskVenvPython }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}
if ($Module2Url -and $MockModule2) { throw '-Module2Url과 -MockModule2는 함께 사용할 수 없습니다.' }
if (-not $MockModule2 -and -not $Module2Url) {
    & $Python -c "import pydantic; assert int(pydantic.__version__.split('.')[0]) >= 2"
    if ($LASTEXITCODE -ne 0) { throw '필요한 패키지가 없습니다. 먼저 .\setup.ps1을 실행하세요.' }
}
function Assert-FreePort([int]$TaskPort) {
    $taskListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $TaskPort)
    try { $taskListener.Start() } catch { throw "포트 $TaskPort 이 사용 중입니다. 기존 서버를 종료하거나 -Port / -Module2Port를 지정하세요." }
    finally { $taskListener.Stop() }
}
Assert-FreePort $Port
if (-not $Module2Url) {
    if ($Port -eq $Module2Port) { throw '웹과 모듈 2의 포트는 달라야 합니다.' }
    Assert-FreePort $Module2Port
}
$taskModule = Join-Path $PSScriptRoot 'backend\module1'
$taskProcess = $null
$taskLogs = Join-Path $taskModule 'data\logs'
New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
try {
    if (-not $Module2Url) {
        $Module2Url = "http://127.0.0.1:$Module2Port"
        $taskScript = if ($MockModule2) { Join-Path $PSScriptRoot 'integration\module2_mock.py' } else { Join-Path $PSScriptRoot 'backend\module2\server.py' }
        $taskMode = if ($MockModule2) { 'mock' } else { 'real' }
        $taskProcess = Start-Process -FilePath $Python -ArgumentList @('-X','utf8',('"'+$taskScript+'"'),'--port',$Module2Port) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskLogs 'module2.stdout.log') -RedirectStandardError (Join-Path $taskLogs 'module2.stderr.log')
        $taskReady = $false
        for ($taskAttempt=0; $taskAttempt -lt 50; $taskAttempt++) {
            if ($taskProcess.HasExited) { throw '모듈 2가 종료되었습니다. backend/module1/data/logs/module2.stderr.log를 확인하세요.' }
            try {
                $taskResponse = Invoke-RestMethod -Uri "$Module2Url/health" -TimeoutSec 1
                if ($taskResponse.mode -eq $taskMode -and $taskResponse.contract_version -eq '2.0.0') { $taskReady = $true; break }
            } catch { }
            Start-Sleep -Milliseconds 150
        }
        if (-not $taskReady) { throw '모듈 2 시작을 확인하지 못했습니다.' }
        if ($taskMode -eq 'real') { Write-Host $taskResponse.message }
    }
    Write-Host "웹 주소: http://127.0.0.1:$Port"
    Write-Host '종료: Ctrl+C'
    if ($OpenBrowser) { Start-Process "http://127.0.0.1:$Port" -WindowStyle Hidden }
    & $Python -X utf8 (Join-Path $taskModule 'server.py') --port $Port --module2-url $Module2Url --module2-timeout 600
    if ($LASTEXITCODE -ne 0) { throw "모듈 1 종료 코드: $LASTEXITCODE" }
} finally {
    if ($null -ne $taskProcess -and -not $taskProcess.HasExited) {
        Stop-Process -Id $taskProcess.Id -ErrorAction SilentlyContinue
    }
}
