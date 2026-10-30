# Image of the agents: Claude Code + the Python dependencies of the MCP servers. No project file is copied here:
# scripts/agent_docker.sh mounts only what each agent needs (.dockerignore keeps .env and the rest out of the build).
# The images are pinned by digest, and the Python packages by hash (requirements.lock): a build gets the same code.
FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f

ARG CLAUDE_CODE_VERSION=2.1.314

COPY --from=node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

WORKDIR /app
COPY requirements.lock /tmp/requirements.lock
# In /app/.venv because .mcp.json starts the servers with .venv/bin/python.
RUN python -m venv /app/.venv && /app/.venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock

RUN useradd --uid 1000 --create-home agent
ENV PYTHONDONTWRITEBYTECODE=1 DISABLE_AUTOUPDATER=1
USER agent
ENTRYPOINT ["claude"]
