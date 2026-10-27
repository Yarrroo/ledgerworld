# syntax=docker/dockerfile:1
# One image for every LedgerWorld process: the API (which also serves the built frontend), and
# the simulation worker. LEDGERWORLD_ROLE picks the process at start (deploy/entrypoint.sh).
# Build from the repository root:  docker build -f deploy/Dockerfile .
# No value is baked in: every setting arrives by name at run time (.env.example).

# ---- frontend: the Vue app, built once; the API serves it from the same origin
FROM node:22-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN --mount=type=cache,target=/root/.npm npm ci --prefix frontend
COPY locales ./locales
COPY frontend ./frontend
# "/" makes every API call relative to the page's own origin
ENV VITE_API_BASE_URL=/
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

# The workspace members; of backend/ only the code, never a checkout's logs, uploads or job dirs
COPY backend/app ./backend/app
COPY backend/scripts ./backend/scripts
COPY packages ./packages
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
