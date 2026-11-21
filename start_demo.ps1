param(
    [string]$Python = "",
    [int]$Port = 8000,
    [int]$MockPort = 8001,
    [string]$Module2Url = "",
    [switch]$OpenBrowser
)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $taskAnaconda = Join-Path $env:USERPROFILE 'anaconda3\python.exe'
    if (Test-Path -LiteralPath $taskAnaconda) { $Python = $taskAnaconda }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}
$taskModule = Join-Path $PSScriptRoot 'backend\module1'
$taskMockProcess = $null
$taskLogs = Join-Path $taskModule 'data\logs'
New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
try {
    if (-not $Module2Url) {
        $Module2Url = "http://127.0.0.1:$MockPort"
        $taskMockScript = Join-Path $PSScriptRoot 'integration\module2_mock.py'
        $taskMockProcess = Start-Process -FilePath $Python -ArgumentList @('-X','utf8',('"'+$taskMockScript+'"'),'--port',$MockPort) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskLogs 'module2_mock.stdout.log') -RedirectStandardError (Join-Path $taskLogs 'module2_mock.stderr.log')
        $taskReady = $false
        for ($taskAttempt=0; $taskAttempt -lt 30; $taskAttempt++) {
            if ($taskMockProcess.HasExited) { throw '모의 서버가 종료되었습니다. 포트 사용 여부와 data/logs를 확인하세요.' }
            try {
                $taskResponse = Invoke-RestMethod -Uri "$Module2Url/health" -TimeoutSec 1
                if ($taskResponse.mode -eq 'mock') { $taskReady = $true; break }
            } catch { }
            Start-Sleep -Milliseconds 150
        }
        if (-not $taskReady) { throw '모의 서버를 시작하지 못했습니다.' }
    }
    Write-Host "웹 주소: http://127.0.0.1:$Port"
    Write-Host "종료: Ctrl+C"
    if ($OpenBrowser) { Start-Process "http://127.0.0.1:$Port" -WindowStyle Hidden }
    & $Python -X utf8 (Join-Path $taskModule 'server.py') --port $Port --module2-url $Module2Url
    if ($LASTEXITCODE -ne 0) { throw "모듈 1 종료 코드: $LASTEXITCODE" }
} finally {
    if ($null -ne $taskMockProcess -and -not $taskMockProcess.HasExited) {
        Stop-Process -Id $taskMockProcess.Id -ErrorAction SilentlyContinue
    }
}
