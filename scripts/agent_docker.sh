#!/bin/bash
# Run an agent (Claude Code and its MCP servers) in a Docker container. Used by search.sh, apply.sh and track.sh.
# The container sees only the files of its own job: .env, .git, tests/ and the other agents' files do not exist in it.
# There is no way around Docker: if it does not run, the agent does not start.
#
# Usage:
#   ./scripts/agent_docker.sh login                     → log in once (the login stays in a Docker volume), or:
#                                                         CLAUDE_CODE_OAUTH_TOKEN=... in .env (`claude setup-token`)
#   ./scripts/agent_docker.sh check                     → checks Docker, the image and the login
#   ./scripts/agent_docker.sh <job> <claude options...> → job: search, search-test, apply, track
#
# Env: OUT_DIR (job apply, checked by apply.sh), MEMORY_DB, MCP_TOOL_TIMEOUT, ANTHROPIC_* (only for a local model).
# AGENT_DOCKER_DRY_RUN=1 prints the `docker run` arguments, one per line, and runs nothing (unit tests).

set -euo pipefail
cd "$(dirname "$0")/.."  # the project root (this script lives in scripts/)

VOLUME="agent-stage-claude"
JOB="${1:-}"
[ $# -gt 0 ] && shift

DRY_RUN="${AGENT_DOCKER_DRY_RUN:-0}"
ENV_FILE="${AGENT_DOCKER_ENV_FILE:-.env}"  # another file only for tests
HASH="$(cat Dockerfile requirements.lock | shasum -a 256 | cut -c1-12)"
IMAGE="agent-stage:$HASH"

prepare_docker() {
  if ! docker info > /dev/null 2>&1; then
    echo "Docker does not run: start Docker Desktop, then try again. The agents never run outside Docker." >&2
    exit 1
  fi
  # The tag holds a hash of the Dockerfile and requirements.lock: a change builds a new image.
  if ! docker image inspect "$IMAGE" > /dev/null 2>&1; then
    echo "▶ Building the Docker image $IMAGE (a few minutes, only the first time)." >&2
    docker build -t "$IMAGE" . >&2
  fi
}

# The value of one NAME=value line of .env. Never printed by this script.
read_secret() {
  [ -f "$ENV_FILE" ] || return 0
  sed -nE "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -1 | sed -E "s/^[\"']//; s/[\"'[:space:]]*$//"
}

# 2 ways to log in: the login of the volume (first choice: the claude.ai connectors need it), or a token of .env.
USE_TOKEN=0
check_login() {
  # The file, not only the volume: `docker run -v` creates an empty volume, and a login can be stopped halfway.
  if docker run --rm -v "$VOLUME:/home/agent" --entrypoint test "$IMAGE" -s /home/agent/.claude/.credentials.json; then
    return 0
  fi
  if [ -n "$(read_secret CLAUDE_CODE_OAUTH_TOKEN)" ]; then
    USE_TOKEN=1
    echo "⚠ No login in the Docker volume: using the token of .env, so the claude.ai connectors (Indeed) are not loaded." >&2
    echo "  To get Indeed back, run ./scripts/agent_docker.sh login once (see README.md)." >&2
    return 0
  fi
  echo "Not logged in. Run \`claude setup-token\` on the Mac and add CLAUDE_CODE_OAUTH_TOKEN=<token> to .env," >&2
  echo "or run ./scripts/agent_docker.sh login once (see README.md)." >&2
  exit 1
}

HARDENING=(--rm --init --read-only --cap-drop ALL --security-opt no-new-privileges
           --pids-limit 256 --memory 2g --tmpfs /tmp:rw,noexec,nosuid,size=256m
           -v "$VOLUME:/home/agent" -w /app)

case "$JOB" in
  login)
    prepare_docker
    # `auth login`, not `/login`: the link is one plain line, so it stays whole when it is copied.
    exec docker run -it "${HARDENING[@]}" "$IMAGE" auth login
    ;;
  check)
    prepare_docker
    check_login
    exit 0
    ;;
  search|search-test|apply|track) ;;
  *)
    echo "Usage: ./scripts/agent_docker.sh login|check|search|search-test|apply|track [claude options...]" >&2
    exit 1
    ;;
esac

# Common to all the jobs. data/ is for the memory server and returned_urls.jsonl: the agents go only through the server.
ARGS=("${HARDENING[@]}"
      -v "$PWD/CLAUDE.md:/app/CLAUDE.md:ro"
      -v "$PWD/.mcp.json:/app/.mcp.json:ro"
      -v "$PWD/mcp:/app/mcp:ro"
      -v "$PWD/.claude/settings.json:/app/.claude/settings.json:ro"
      -v "$PWD/data:/app/data")
mkdir -p data

NEEDS_API_KEY=0
case "$JOB" in
  search|search-test)
    mkdir -p reports
    ARGS+=(-v "$PWD/.claude/skills/search-offers:/app/.claude/skills/search-offers:ro"
           -v "$PWD/reports:/app/reports")
    if [ "$JOB" = "search-test" ]; then
      ARGS+=(-v "$PWD/tests/fake_offers.json:/app/tests/fake_offers.json:ro")
    else
      # The search settings. `docker run -v` would create a missing file as a folder: stop first.
      if [ ! -f config/search.json ] && [ "$DRY_RUN" != "1" ]; then
        echo "config/search.json is missing: copy config/search.example.json, then fill it in (see README.md)." >&2
        exit 1
      fi
      ARGS+=(-v "$PWD/config/search.json:/app/config/search.json:ro")
      NEEDS_API_KEY=1
    fi
    ;;
  apply)
    if [ -z "${OUT_DIR:-}" ]; then
      echo "agent_docker.sh apply: OUT_DIR is missing." >&2
      exit 1
    fi
    mkdir -p "$OUT_DIR"
    # Only this offer's folder, and only the 2 profile files of the skill (not cv.pdf).
    ARGS+=(-v "$PWD/.claude/skills/prepare-application:/app/.claude/skills/prepare-application:ro"
           -v "$PWD/profile/cv.md:/app/profile/cv.md:ro"
           -v "$PWD/profile/email-base.md:/app/profile/email-base.md:ro"
           -v "$PWD/$OUT_DIR:/app/$OUT_DIR")
    # Only for the details of an `ats` offer (its board must be in the settings).
    if [ -f config/search.json ] || [ "$DRY_RUN" = "1" ]; then
      ARGS+=(-v "$PWD/config/search.json:/app/config/search.json:ro")
    fi
    NEEDS_API_KEY=1
    ;;
  track)
    ARGS+=(-v "$PWD/.claude/skills/tracking:/app/.claude/skills/tracking:ro")
    ;;
esac

# Another memory file (tests, trial of pipeline.sh): mount only its folder. Never a folder that holds the project or
# everything else of /tmp: the agent would see these files.
if [ -n "${MEMORY_DB:-}" ]; then
  mkdir -p "$(dirname "$MEMORY_DB")"
  DB_DIR="$(cd "$(dirname "$MEMORY_DB")" && pwd -P)"
  case "$DB_DIR" in
    /tmp|/private/tmp|/var/tmp|/private/var/tmp)
      echo "MEMORY_DB must be in its own folder (e.g. /tmp/check/offers.db), not directly in $DB_DIR." >&2
      exit 1
      ;;
  esac
  if [[ "$(pwd -P)/" == "$DB_DIR/"* ]]; then
    echo "MEMORY_DB must be in its own folder: $DB_DIR holds the project." >&2
    exit 1
  fi
  ARGS+=(-v "$DB_DIR:/memory" -e "MEMORY_DB=/memory/$(basename "$MEMORY_DB")")
fi

[ -n "${MCP_TOOL_TIMEOUT:-}" ] && ARGS+=(-e "MCP_TOOL_TIMEOUT=$MCP_TOOL_TIMEOUT")

# A local model (apply.sh): the host is reached through host.docker.internal.
if [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
  ARGS+=(-e ANTHROPIC_BASE_URL -e ANTHROPIC_AUTH_TOKEN -e ANTHROPIC_API_KEY)
fi

# An interactive chat needs a terminal. With a pipe (claude -p | progress.py), no terminal: stdout stays clean.
if [ -t 0 ] && [ -t 1 ]; then
  ARGS+=(-it)
fi

if [ "$DRY_RUN" = "1" ]; then
  printf '%s\n' "${ARGS[@]}" "$IMAGE" "$@"
  exit 0
fi

prepare_docker
check_login

# Only these secrets leave .env. `-e NAME` without a value: it is not on the command line, so `ps` does not show it.
if [ "$NEEDS_API_KEY" = "1" ]; then
  LBA_API_KEY="$(read_secret LBA_API_KEY)"
  export LBA_API_KEY
  ARGS+=(-e LBA_API_KEY)
fi
if [ "$USE_TOKEN" = "1" ]; then
  CLAUDE_CODE_OAUTH_TOKEN="$(read_secret CLAUDE_CODE_OAUTH_TOKEN)"
  export CLAUDE_CODE_OAUTH_TOKEN
  ARGS+=(-e CLAUDE_CODE_OAUTH_TOKEN)
fi

docker run "${ARGS[@]}" "$IMAGE" "$@"
