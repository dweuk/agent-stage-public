#!/bin/bash
# Write a DRAFT application email for one offer, from my email base, in a Docker container
# (scripts/agent_docker.sh). Nothing is sent.
#
# Usage:
#   ./scripts/apply.sh la_bonne_alternance:0123456789abcdef01234567 → from an offer id (see `find` in the tracking)
#   ./scripts/apply.sh "Nova"                           → from a company name
#   ./scripts/apply.sh "$(pbpaste)"                             → from the offer text in the clipboard (macOS)
#   MODEL=opus ./scripts/apply.sh ...                           → choose another model (default: sonnet)
#   MODEL=ollama:mistral-small3.2 ./scripts/apply.sh ...        → a local model served by Ollama
#   OUT_DIR=applications/test ./scripts/apply.sh ...            → write the drafts in another folder (under applications/)
#
# Used by scripts/apply_all.sh with BATCH=1: no chat, one answer, then exit.
# Needs: profile/cv.md (my CV, plain text) and profile/email-base.md (the base of my emails).
# Output: applications/ (ignored by git). To quit the chat: /exit (or Ctrl+D).

set -euo pipefail
cd "$(dirname "$0")/.."  # the project root (this script lives in scripts/)

if [ $# -eq 0 ]; then
  echo "Usage: ./scripts/apply.sh <offer id | company | offer text>" >&2
  exit 1
fi
if [ ! -f profile/cv.md ]; then
  echo "Missing profile/cv.md (my CV as plain text)." >&2
  exit 1
fi
if [ ! -f profile/email-base.md ]; then
  echo "Missing profile/email-base.md (the base of my emails, see README.md)." >&2
  exit 1
fi
export OUT_DIR="${OUT_DIR:-applications}"
# Each sub-folder name starts with a letter, a digit or _: no "." or ".." (no way out of applications/).
if [[ ! "$OUT_DIR" =~ ^applications(/[A-Za-z0-9_][A-Za-z0-9._-]*)*$ ]]; then
  echo "OUT_DIR must be applications or a sub-folder of applications/ (letters, digits, . _ -, not starting with . or -)." >&2
  exit 1
fi
mkdir -p "$OUT_DIR"

TODAY="$(LC_TIME=C date '+%Y-%m-%d (%A)')"
PROMPT="Application. Today's date: $TODAY. Answer me in French. Output folder: $OUT_DIR. The offer (id, company name, or pasted text): $*"

# Only what the skill needs: read the offer, read my profile, write in applications/.
# No tracking write, no search tool. Everything else is refused without asking (dontAsk).
ALLOWED_TOOLS=(
  "Skill"
  "Read(./profile/**)"
  "Read(./$OUT_DIR/**)"   # offer-data.md, written by apply_all.sh
  "Edit(./$OUT_DIR/**)"   # also covers Write (file creation). Only OUT_DIR: the check below reads only there
  "mcp__memory__find"
  "mcp__la-bonne-alternance__get_offer_details"
  "mcp__ats__get_offer_details"
)

# Always refused (deny beats allow). Same closing as scripts/search.sh: dontAsk still runs file reads
# in this folder and read-only shell commands, so the sensitive ones are blocked here.
DENIED_TOOLS=(
  "Bash"
  "WebFetch"
  "WebSearch"
  "Grep"
  "Read(./.env)"
  "Read(./.env.*)"
  "Read(./tests/**)"
  "Read(./data/**)"
  "Read(./.git/**)"
  "Read(./.claude/settings.local.json)"
  "Read(./.venv/**)"
  # In the container: my login (home folder) and the secrets in the environment of the process.
  "Read(//home/agent/**)"
  "Read(//proc/**)"
  "Edit(./profile/**)"
  "mcp__memory__add_tracking"
  "mcp__memory__add_offer"
  "mcp__memory__save_evaluations"
  "mcp__memory__filter_already_seen"
  "mcp__memory__find_reposts"
  # Without --strict-mcp-config, ALL my claude.ai connectors are loaded: refuse all but the 2 Indeed tools.
  "mcp__claude_ai_Indeed__get_company_data"
  "mcp__claude_ai_Indeed__get_resume"       # my Indeed CV: never for an agent that reads untrusted offers
  "mcp__claude_ai_Google_Drive"
  "mcp__claude_ai_monday_com"
  "mcp__claude_ai_Canva"
  "mcp__claude_ai_Claude_Docs"
  "Edit(./reports/**)"
  "Edit(./data/**)"
)

# The claude.ai Indeed connector only when the WHOLE request is an `indeed:` id or an Indeed link, or when
# apply_all.sh gives an Indeed link in OFFER_LINK. Never because the word is somewhere in a text: a title or a pasted
# offer can contain it. Its search keyword is free text sent to Indeed: a prompt injection could use it to leak my CV.
# Other offers: --strict-mcp-config, so no claude.ai connector is loaded at all.
INDEED_ID_REGEX='^indeed:[^|]+[|][^|]+[|][0-9]{4}-[0-9]{2}-[0-9]{2}$'
INDEED_LINK_REGEX='^https://([a-z0-9-]+[.])*indeed[.]com(/[^[:space:]]*)?$'
MCP_OPTIONS=(--mcp-config .mcp.json --strict-mcp-config)
shopt -s nocasematch
if [[ "$*" =~ $INDEED_ID_REGEX || "$*" =~ $INDEED_LINK_REGEX || "${OFFER_LINK:-}" =~ $INDEED_LINK_REGEX ]]; then
  ALLOWED_TOOLS+=(
    "mcp__claude_ai_Indeed__search_jobs"       # only to find the Indeed offer again
    "mcp__claude_ai_Indeed__get_job_details"   # (the Indeed job id changes at each call, so we search first)
  )
  # No --strict-mcp-config: the Indeed connector must be visible. The other connectors are in DENIED_TOOLS.
  MCP_OPTIONS=(--mcp-config .mcp.json)
fi
shopt -u nocasematch

MODEL="${MODEL:-sonnet}"

# A local model: Claude Code talks to Ollama (Anthropic-compatible API) instead of Anthropic.
# Same tools, same allow/deny rules. Ollama must run (ollama serve) with a big context window,
# e.g. OLLAMA_CONTEXT_LENGTH=32768 ollama serve.
if [[ "$MODEL" == ollama:* ]]; then
  MODEL="${MODEL#ollama:}"
  export ANTHROPIC_BASE_URL="${OLLAMA_URL:-http://host.docker.internal:11434}"
  export ANTHROPIC_AUTH_TOKEN="ollama"
  export ANTHROPIC_API_KEY=""
fi

# Safety: dontAsk refuses every tool that is not allowed above.
# The prompt comes first: --tools, --allowedTools and --disallowedTools take all the words that follow them.
# One options array, never empty: bash 3.2 (macOS) with `set -u` fails on "${empty_array[@]}".
# --tools: the only built-in tools the model even sees (the skill needs nothing else). Safer (no Bash at all),
# and a much smaller prompt: a local model reads the whole prompt again at each step, so it is much faster.
OPTIONS=("$PROMPT" --model "$MODEL" --permission-mode dontAsk --tools "Skill,Read,Write,Edit"
         --allowedTools "${ALLOWED_TOOLS[@]}" --disallowedTools "${DENIED_TOOLS[@]}"
         "${MCP_OPTIONS[@]}")
if [ "${BATCH:-0}" = "1" ]; then
  # stream-json + --verbose: one JSON event per line, read by progress.py to show each step live
  # (as in search.sh). Without it, `claude -p` prints nothing until the end: 10 minutes of silence.
  OPTIONS=(-p "${OPTIONS[@]}" --output-format stream-json --verbose)
fi

# Files written after this marker are the drafts of this run (checked below).
MARKER="$(mktemp)"
trap 'rm -f "$MARKER"' EXIT

set +e
if [ "${BATCH:-0}" = "1" ]; then
  ./scripts/agent_docker.sh apply "${OPTIONS[@]}" | .venv/bin/python scripts/progress.py
  STATUS=${PIPESTATUS[0]}
else
  ./scripts/agent_docker.sh apply "${OPTIONS[@]}"
  STATUS=$?
fi
set -e

# Check the new drafts: the offer text may contain a prompt injection. An image or an HTML tag in a
# Markdown file can send data (e.g. my phone number in the URL) as soon as a preview opens it.
# So: no image, no HTML tag, no URL that is not already written in my CV or my email base, and no file other than .md.
URL_REGEX='([a-z][a-z0-9+.-]*://|www\.)[^][()<>"'\'' ]+'
# A tag name can be followed by a space, a tab, ">", "/" or the end of the line (the attributes on the next line).
TAG_REGEX='!\[|<(img|a|iframe|frame|script|link|meta|base|object|embed|svg|math|style|form|input|video|audio|source|track|picture|body|table)([[:space:]/>]|$)'
# An attribute that loads something, even without a known tag; and "//host" URLs (no scheme, missed by URL_REGEX).
ATTR_REGEX='(^|[^a-z])(src|srcset|href|poster|background|action|formaction)[[:space:]]*=|(^|[^:])//[a-z0-9-]+\.[a-z]'
MY_URLS="$(grep -ohiE "$URL_REGEX" profile/cv.md profile/email-base.md | sed -E 's/[.,;:!?]+$//' || true)"
# Text written by the agent: no control character (terminal escape codes) reaches the terminal.
printable() { LC_ALL=C tr -d '\000-\010\013-\037\177' | LC_ALL=C sed -E $'s/\xc2[\x80-\x9f]//g'; }
DANGER=0
while IFS= read -r FILE; do
  [ -n "$FILE" ] || continue
  if [[ "$FILE" != *.md ]]; then
    echo "⚠ DANGER: unexpected file (the drafts are .md only): $FILE" | printable >&2
    DANGER=1
  fi
  if grep -qiE "$TAG_REGEX|$ATTR_REGEX" "$FILE"; then
    grep -inE "$TAG_REGEX|$ATTR_REGEX" "$FILE" | printable >&2
    echo "⚠ DANGER: image, HTML tag or link attribute in $FILE (lines above)." | printable >&2
    DANGER=1
  fi
  while IFS= read -r URL; do
    [ -n "$URL" ] || continue
    if ! grep -qxF -- "$URL" <<< "$MY_URLS"; then
      echo "⚠ DANGER: URL not in my CV or email base, in $FILE: $URL" | printable >&2
      DANGER=1
    fi
  done <<< "$(grep -oiE "$URL_REGEX" "$FILE" | sed -E 's/[.,;:!?]+$//' || true)"
done <<< "$(find "$OUT_DIR" -type f ! -name .DS_Store -newer "$MARKER")"   # every new file, in sub-folders too

if [ "$DANGER" = "1" ]; then
  echo "⚠ Do NOT open these drafts in a Markdown preview, and do not send them: read them as plain text first." >&2
  exit 3
fi
exit "$STATUS"
