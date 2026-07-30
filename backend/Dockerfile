# TrustBoard dashboard backend (FastAPI). Serves the history from SQLite and
# does not need DataHub. Build from the repo root:
#   docker build -f backend/Dockerfile -t trustboard-backend .
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY config.py ./config.py
COPY backend ./backend
# /api/model serves the weights, cut-offs and coverage floor straight from the
# scorer, so the rules the dashboard renders cannot drift from the ones that
# produced the numbers. That makes this module a runtime dependency of the API,
# not just of the agents. It was missing here, and because the import is lazy the
# container started clean and only failed when something asked for the model.
# It is pure stdlib, so it costs the image nothing.
COPY scoring ./scoring

ENV DATABASE_URL=sqlite:////data/trustboard.db
ENV CORS_ORIGINS=*
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
