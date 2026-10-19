# 백엔드(FastAPI :8000) + 프론트엔드(Vite :5173)를 한 터미널에서 실행한다.
#   .\dev.cmd          실행 (DB가 없으면 데모 데이터 자동 생성)
#   .\dev.cmd -Seed    데모 데이터를 오늘 날짜 기준으로 다시 만든 뒤 실행
# Ctrl+C 한 번으로 둘 다 종료된다.
param([switch]$Seed)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$be = Join-Path $root 'backend'
$fe = Join-Path $root 'frontend'
$py = Join-Path $be '.venv\Scripts\python.exe'

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

foreach ($port in 8000, 5173) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "포트 $port 이(가) 이미 사용 중입니다. 기존 서버를 종료한 뒤 다시 실행하세요." -ForegroundColor Red
        exit 1
    }
}

# 최초 1회 설치
if (-not (Test-Path $py)) {
    Step '백엔드 가상환경 생성 및 패키지 설치'
    python -m venv (Join-Path $be '.venv')
    & $py -m pip install -q -r (Join-Path $be 'requirements.txt')
}
if (-not (Test-Path (Join-Path $fe 'node_modules'))) {
    Step '프론트엔드 패키지 설치'
    Push-Location $fe; npm install; Pop-Location
}

if ($Seed -or -not (Test-Path (Join-Path $be 'allostar.db'))) {
    Step '데모 데이터 생성'
    Push-Location $be; & $py -m app.seed; Pop-Location
}

# 시연용 실행이므로 데모 모드(데모 계정 바로 입장·인증번호 화면 표시)를 켠다. 코드 기본값은 꺼짐.
if (-not $env:DEMO_MODE) { $env:DEMO_MODE = 'true' }

# 백엔드·프론트엔드를 각각 '숨은 별도 콘솔'에서 실행하고, 이 터미널에는 두 로그를 모아 보여준다.
# 같은 콘솔에서 실행하면 uvicorn --reload가 Windows에서 워커를 재시작할 때 보내는 Ctrl+C 이벤트가
# 콘솔 전체(npm/Vite 포함)에 전달돼, 코드를 고칠 때마다 개발 서버가 통째로 꺼진다.
$logDir = Join-Path $root '.dev-logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$logs = @{
    api     = @{ out = (Join-Path $logDir 'api.out.log'); err = (Join-Path $logDir 'api.err.log') }
    web     = @{ out = (Join-Path $logDir 'web.out.log'); err = (Join-Path $logDir 'web.err.log') }
}
foreach ($l in $logs.Values) { Set-Content -Path $l.out, $l.err -Value $null }
$env:PYTHONIOENCODING = 'utf-8'

Step '백엔드 시작  http://localhost:8000/docs'
$backend = Start-Process -FilePath $py -WorkingDirectory $be -WindowStyle Hidden -PassThru `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000' `
    -RedirectStandardOutput $logs.api.out -RedirectStandardError $logs.api.err
Step '프론트엔드 시작  http://localhost:5173'
$frontend = Start-Process -FilePath 'cmd.exe' -WorkingDirectory $fe -WindowStyle Hidden -PassThru `
    -ArgumentList '/c', 'npm run dev' `
    -RedirectStandardOutput $logs.web.out -RedirectStandardError $logs.web.err
Step '실행 중 (종료: Ctrl+C)'

function Open-Log($path) {
    $fs = [System.IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
    New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
}
$readers = @(
    @{ r = (Open-Log $logs.api.out); tag = 'api' }, @{ r = (Open-Log $logs.api.err); tag = 'api' },
    @{ r = (Open-Log $logs.web.out); tag = 'web' }, @{ r = (Open-Log $logs.web.err); tag = 'web' }
)

try {
    while ($true) {
        $idle = $true
        foreach ($x in $readers) {
            while ($null -ne ($line = $x.r.ReadLine())) {
                $idle = $false
                $color = if ($x.tag -eq 'api') { 'Gray' } else { 'DarkCyan' }
                Write-Host "[$($x.tag)] $line" -ForegroundColor $color
            }
        }
        if ($backend.HasExited) { Write-Host '백엔드가 종료되었습니다. 위 로그를 확인하세요.' -ForegroundColor Red; break }
        if ($frontend.HasExited) { Write-Host '프론트엔드가 종료되었습니다. 위 로그를 확인하세요.' -ForegroundColor Red; break }
        if ($idle) { Start-Sleep -Milliseconds 200 }
    }
}
finally {
    Step '서버 종료'
    foreach ($x in $readers) { $x.r.Dispose() }
    # uvicorn --reload·npm은 자식 프로세스를 띄우므로 프로세스 트리 전체를 종료
    foreach ($p in $backend, $frontend) { taskkill /PID $p.Id /T /F *> $null }
}
