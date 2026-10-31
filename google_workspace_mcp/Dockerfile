FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/google_workspace_mcp_patch

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       curl \
       jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir workspace-mcp==2.3.0 fastmcp==4.1.4 mcp==2.3.0

COPY run.sh /run.sh
COPY patches/sitecustomize.py /opt/google_workspace_mcp_patch/sitecustomize.py
RUN chmod +x /run.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["/run.sh"]
