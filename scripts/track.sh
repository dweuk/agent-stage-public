#!/bin/bash
# Open a chat with the agent to record or look up my tracking, in a Docker container (scripts/agent_docker.sh).
#
# Usage:
#   ./scripts/track.sh                                          → shows the last rows, then we chat
#   ./scripts/track.sh "j'ai postulé chez Nova hier"    → starts with this message
#   MODEL=opus ./scripts/track.sh                               → choose another model (default: sonnet)
#
# To quit: /exit (or Ctrl+D).

set -euo pipefail
cd "$(dirname "$0")/.."  # the project root (this script lives in scripts/)

TODAY="$(LC_TIME=C date '+%Y-%m-%d (%A)')"
if [ $# -gt 0 ]; then
  MESSAGE="My message (in French): $*"
else
  MESSAGE="Show me my last 5 tracking rows, then ask me what I want to record."
fi
PROMPT="Tracking. Today's date: $TODAY. Answer me in French. $MESSAGE"

# Only the tracking tools. Everything else is refused without asking (dontAsk).
ALLOWED_TOOLS=(
  "Skill"
  "mcp__memory__find"
  "mcp__memory__history"
  "mcp__memory__add_tracking"
  "mcp__memory__add_offer"
)

# Always refused (deny beats allow). dontAsk still runs file reads in this folder and read-only
# shell commands (`cat`, `ls`…): these rules block them. The tracking needs no file at all.
DENIED_TOOLS=(
  "Bash"
  "WebFetch"
  "WebSearch"
  "Read"
  "Glob"
  "Grep"
  "Edit"
)

MODEL="${MODEL:-sonnet}"

# The prompt comes first: --allowedTools and --disallowedTools take all the words that follow them.
./scripts/agent_docker.sh track "$PROMPT" --model "$MODEL" --permission-mode dontAsk \
       --allowedTools "${ALLOWED_TOOLS[@]}" --disallowedTools "${DENIED_TOOLS[@]}" \
       --mcp-config .mcp.json --strict-mcp-config
