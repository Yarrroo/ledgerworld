# syntax=docker/dockerfile:1
# One image for every LedgerWorld process: the API (which also serves the built frontend), and
# the simulation worker. LEDGERWORLD_ROLE picks the process at start (deploy/entrypoint.sh).
# Build from the repository root:
#   docker build -f deploy/Dockerfile --build-arg VITE_SOURCE_URL=<public source URL> .
# No value is baked in but the source link: every setting arrives by name at run time
# (.env.example), and VITE_SOURCE_URL, which the frontend bundle carries, arrives as a build argument.

# ---- frontend: the Vue app, built once; the API serves it from the same origin
FROM node:22-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN --mount=type=cache,target=/root/.npm npm ci --prefix frontend
COPY locales ./locales
COPY frontend ./frontend
# "/" makes every API call relative to the page's own origin
ENV VITE_API_BASE_URL=/
# Every page footer links the source (AGPL-3.0 §13); a bundle built without it would omit the link
ARG VITE_SOURCE_URL
# An http(s) URL with a host and no space, quote or angle bracket, or the build stops here
RUN case "$VITE_SOURCE_URL" in *[[:space:]\"\'\<\>]*) false ;; http://[!/]*|https://[!/]*) ;; *) false ;; esac || { echo "VITE_SOURCE_URL must be the public http(s) URL of this source: --build-arg VITE_SOURCE_URL=<url>" >&2; exit 1; }
RUN npm --prefix frontend run build

# ---- app: Python 3.12 slim, the uv workspace installed from the lockfile
FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app

# Dependencies first, so a source change does not reinstall them
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml ./backend/
COPY packages/oasis-finance/pyproject.toml ./packages/oasis-finance/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-workspace

# The workspace members; of backend/ only the code, never a checkout's logs, uploads or job dirs.
# .dockerignore matches its dotenv and __pycache__ entries at the context root only, so each
# code copy excludes them at any depth itself.
COPY --exclude=**/.env --exclude=**/__pycache__ backend/app ./backend/app
COPY --exclude=**/.env --exclude=**/__pycache__ backend/scripts ./backend/scripts
COPY --exclude=**/.env --exclude=**/__pycache__ packages ./packages
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# The data the code reads at run time, by repo-root relative path
COPY contracts ./contracts
COPY fixtures ./fixtures
COPY scenarios ./scenarios
COPY locales ./locales
COPY prp/2026-10-20-ledgerworld/design/modules/execution ./prp/2026-10-20-ledgerworld/design/modules/execution
COPY --from=frontend /src/frontend/dist ./frontend/dist
COPY deploy/entrypoint.sh ./deploy/entrypoint.sh

RUN useradd --system --uid 10001 --home-dir /app ledgerworld \
    && mkdir -p backend/uploads backend/var backend/logs \
    && chown -R ledgerworld backend/uploads backend/var backend/logs
USER ledgerworld
WORKDIR /app/backend

ENV LEDGERWORLD_ROLE=api
EXPOSE 5001
ENTRYPOINT ["bash", "/app/deploy/entrypoint.sh"]
