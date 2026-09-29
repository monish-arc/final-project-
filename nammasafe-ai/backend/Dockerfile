# --- Backend image for NammaSafe AI / SAFE_MOVE_AI ---
# Python 3.13-slim is used (instead of 3.14) so every dependency in
# requirements.txt installs from pre-built wheels on Linux; the code itself is
# version-agnostic and runs identically on the 3.14 local venv.
#
# docker-compose.yml bind-mounts ./nammasafe-ai/backend over /app, so this
# image only supplies the runtime and dependencies; the code served at runtime
# is the checked-out copy. The gitignored backend/.env (EARTHDATA creds for
# GPM/GES DISC) is bind-mounted automatically when present. Without it the API
# degrades to the labelled NOT_CONFIGURED state — never fabricated data.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY .env.example ./.env.example

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]