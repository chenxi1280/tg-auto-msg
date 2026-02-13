FROM node:20-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/h5/package*.json ./
RUN npm ci
COPY frontend/h5/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY main.py /app/main.py
COPY sql /app/sql
COPY .env.example /app/.env.example

# H5 静态构建产物（供 FastAPI 直接挂载）
COPY --from=frontend-builder /frontend/dist /app/frontend/h5/dist

RUN mkdir -p /app/logs /app/uploads

EXPOSE 8000
CMD ["python", "main.py"]
