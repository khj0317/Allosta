#!/usr/bin/env bash
# Docker 없이 백엔드(FastAPI :8000) + 프론트엔드(Vite :5173)를 한 터미널에서 실행한다. (macOS/Linux)
#   ./dev.sh          실행 (DB가 없으면 데모 데이터 자동 생성)
#   ./dev.sh --seed   데모 데이터를 오늘 날짜 기준으로 다시 만든 뒤 실행
# Ctrl+C 한 번으로 둘 다 종료된다.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BE="$ROOT/backend"
FE="$ROOT/frontend"
PY="$BE/.venv/bin/python"

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }

for port in 8000 5173; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "포트 $port 이(가) 이미 사용 중입니다. 기존 서버를 종료한 뒤 다시 실행하세요." >&2
    exit 1
  fi
done

if [ ! -x "$PY" ]; then
  step '백엔드 가상환경 생성 및 패키지 설치'
  python3 -m venv "$BE/.venv"
  "$PY" -m pip install -q -r "$BE/requirements.txt"
fi
if [ ! -d "$FE/node_modules" ]; then
  step '프론트엔드 패키지 설치'
  (cd "$FE" && npm install)
fi

if [ "${1:-}" = "--seed" ] || [ ! -f "$BE/allostar.db" ]; then
  step '데모 데이터 생성'
  (cd "$BE" && "$PY" -m app.seed)
fi

step '백엔드 시작  http://localhost:8000/docs'
(cd "$BE" && exec "$PY" -m uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!
# uvicorn --reload 는 자식 프로세스를 띄우므로 프로세스 그룹째 정리
trap 'step "서버 종료"; pkill -P "$BACKEND_PID" 2>/dev/null; kill "$BACKEND_PID" 2>/dev/null; wait 2>/dev/null' EXIT INT TERM

step '프론트엔드 시작  http://localhost:5173  (종료: Ctrl+C)'
cd "$FE" && npm run dev
