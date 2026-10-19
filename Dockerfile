# 단일 컨테이너 배포용 이미지 (Render 등). 화면(React 빌드)과 API를 서버 하나가 함께 서빙한다.
#   docker build -t allostar . && docker run -p 8000:8000 -e DEMO_MODE=true allostar  →  http://localhost:8000
# 로컬 개발·시연은 docker compose(백엔드 + nginx 2개 컨테이너)를 그대로 써도 된다.

# 1) 프론트엔드 빌드: 타입체크 + 정적 번들
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2) API 서버 + 정적 파일
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/allostar.db \
    STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/docker-entrypoint.sh ./
COPY --from=web /web/dist ./static
RUN chmod +x docker-entrypoint.sh && mkdir -p /data

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
