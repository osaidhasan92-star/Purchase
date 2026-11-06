FROM node:22-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY frontend frontend
RUN npm run build:frontend

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && useradd --create-home --uid 10001 purchase
COPY --chown=purchase:purchase . .
COPY --from=frontend --chown=purchase:purchase /build/frontend-dist /app/frontend-dist
RUN mkdir -p /app/instance && chown purchase:purchase /app/instance
USER purchase
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60", "backend.app:app"]
