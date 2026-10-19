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

Step '백엔드 시작  http://localhost:8000/docs'
$backend = Start-Process -FilePath $py -WorkingDirectory $be -NoNewWindow -PassThru `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000'

try {
    Step '프론트엔드 시작  http://localhost:5173  (종료: Ctrl+C)'
    Push-Location $fe
    npm run dev
}
finally {
    Pop-Location
    Step '서버 종료'
    # uvicorn --reload는 자식 프로세스를 띄우므로 프로세스 트리 전체를 종료
    taskkill /PID $backend.Id /T /F *> $null
}
