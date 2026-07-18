# Backend del dashboard TrustBoard (FastAPI). Sirve el historico desde SQLite;
# no necesita DataHub. Construir desde la raiz del repo:
#   docker build -f backend/Dockerfile -t trustboard-backend .
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY config.py ./config.py
COPY backend ./backend

ENV DATABASE_URL=sqlite:////data/trustboard.db
ENV CORS_ORIGINS=*
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
