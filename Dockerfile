# ============ Build Stage ============
FROM python:3.12-slim AS builder

ARG VERSION=0.0.0

# Pass the version to hatch-vcs (no .git directory in the build context)
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION} \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml uv.lock readme.rst ./

# Install Python dependencies only
RUN uv sync --locked --no-dev --no-install-project

# Copy source code
COPY awspub/ ./awspub/

# Install awspub package itself
RUN uv sync --locked --no-dev --no-editable

# ============ Runtime Stage ============
FROM python:3.12-slim

# Install runtime dependencies (HTTPS support for AWS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and application directory
ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} awspub && \
    useradd -u ${UID} -g awspub -m -d /home/awspub awspub && \
    mkdir -p /app /data && \
    chmod 755 /app && \
    chmod 1777 /data && \
    chmod 755 /home/awspub

WORKDIR /data

# Copy Python virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy the actual source code from the builder
COPY --from=builder /app/awspub /app/awspub

RUN chmod -R a+rX /app

# Configure Python environment
ENV PATH="/app/.venv/bin:$PATH" \
    HOME="/home/awspub" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER awspub

ENTRYPOINT ["awspub"]
CMD ["--help"]
