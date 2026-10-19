#!/bin/sh
# DB가 없거나 SEED_ON_START=always 이면 데모 데이터를 (오늘 날짜 기준으로) 생성한 뒤 API를 띄운다.
set -e

DB_FILE="${DATABASE_URL#sqlite:///}"
if [ "$SEED_ON_START" = "always" ] || [ ! -f "$DB_FILE" ]; then
    python -m app.seed
fi

# PORT: 호스팅 서비스(Render 등)가 지정하는 포트. 없으면 8000
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
