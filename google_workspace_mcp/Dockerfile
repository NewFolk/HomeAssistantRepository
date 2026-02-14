FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       curl \
       jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir workspace-mcp==1.11.1 \
    && python - <<'PY'
import pathlib
import site

scope_file = None
for sp in site.getsitepackages():
    candidate = pathlib.Path(sp) / "auth" / "scopes.py"
    if candidate.exists():
        scope_file = candidate
        break

if scope_file is None:
    raise SystemExit("Could not find workspace-mcp auth/scopes.py to patch")

text = scope_file.read_text(encoding="utf-8")
if "mcp:tools" not in text:
    text = text.replace(
        'OPENID_SCOPE = "openid"\n',
        'OPENID_SCOPE = "openid"\nMCP_TOOLS_SCOPE = "mcp:tools"\n',
    )
    text = text.replace(
        'BASE_SCOPES = [USERINFO_EMAIL_SCOPE, USERINFO_PROFILE_SCOPE, OPENID_SCOPE]',
        'BASE_SCOPES = [USERINFO_EMAIL_SCOPE, USERINFO_PROFILE_SCOPE, OPENID_SCOPE, MCP_TOOLS_SCOPE]',
    )
    scope_file.write_text(text, encoding="utf-8")

print(f"Patched scopes for MCP compatibility: {scope_file}")
PY

COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["/run.sh"]
