# Image unique pour Coolify : FastAPI sert le front buildé et /ws/audio sur la même origine.
# Le HTTPS (obligatoire pour getUserMedia) est assuré par le proxy de Coolify.

# --- Front : build Vite (le module partagé vendor/edth est importé tel quel via l'alias) ---
FROM node:24-slim AS front
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY vendor/ /src/vendor/
COPY contracts/ /src/contracts/
COPY web/ ./
RUN npm run build

# --- Runtime : Python + uv, dépendances de prod uniquement ---
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    FRONT_DIR=/app/static \
    RECORDINGS_DIR=/data/recordings \
    HF_HOME=/data/hf
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY packages/audio-capture/pyproject.toml packages/audio-capture/
COPY packages/distance-estimation/pyproject.toml packages/distance-estimation/
COPY packages/features/pyproject.toml packages/features/
COPY packages/localization/pyproject.toml packages/localization/
COPY services/api/pyproject.toml services/api/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --package api --no-install-workspace
COPY packages/ packages/
COPY services/ services/
# Contrat partagé (profils) lu au démarrage : contracts/profiles.json relatif à WORKDIR.
COPY contracts/ contracts/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --package api --no-editable
COPY --from=front /src/web/dist/ ./static/

# /data : enregistrements et cache Hugging Face du modèle (DISTANCE_ESTIMATOR=model) ; un volume
# monté ici évite de retélécharger la release à chaque redémarrage.
RUN useradd --system --uid 10001 crozidrone && mkdir -p /data/recordings /data/hf \
    && chown -R crozidrone /data
USER crozidrone

EXPOSE 8000
# start-period : avec le modèle, téléchargement de la release + import de torch + parité au démarrage.
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')" || exit 1
# --proxy-headers : derrière Traefik (Coolify), pour que les logs voient le vrai client.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
