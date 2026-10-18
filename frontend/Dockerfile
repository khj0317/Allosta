# 1) 빌드: 타입체크 + 정적 번들
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# 2) 서빙: nginx가 정적 파일을 주고 /api 는 백엔드로 프록시 (개발 환경의 Vite 프록시와 동일한 구조)
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
