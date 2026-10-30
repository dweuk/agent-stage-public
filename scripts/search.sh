#!/bin/bash
# Run the offer search agent, in a Docker container (scripts/agent_docker.sh).
#
# Usage:
#   ./scripts/search.sh               → normal mode (real MCP sources)
#   ./scripts/search.sh test          → test mode (tests/fake_offers.json)
#   MODEL=opus ./scripts/search.sh test   → choose another model (default: sonnet)

set -euo pipefail
cd "$(dirname "$0")/.."  # the project root (this script lives in scripts/)

MODE="${1:-normal}"
if [ "$MODE" != "normal" ] && [ "$MODE" != "test" ]; then
  echo "Usage: $0 [test]" >&2
  exit 1
fi

# The agent cannot read the time by itself (no shell): we give it.
NOW="$(date '+%Y-%m-%d %H:%M')"
PROMPT="Run the offer search in $MODE mode. Launch date and time: $NOW."

# Only these tools are allowed. Everything else that needs approval is refused without asking (dontAsk).
ALLOWED_TOOLS=(
  "Skill"
  "Read(./.claude/skills/search-offers/**)"   # criteria.md, searches.md, report-template.md
  "Read(./tests/fake_offers.json)"            # test mode
  "Glob"                 # to check which reports already exist (Glob(path) rules never match: see README)
  "Edit(./reports/**)"   # also covers Write (file creation)
  "mcp__memory__filter_already_seen"   # only these 3 memory tools:
  "mcp__memory__find_reposts"          # the search agent never touches my tracking
  "mcp__memory__save_evaluations"
  "mcp__la-bonne-alternance__search_offers"
  "mcp__la-bonne-alternance__get_offer_details"
  "mcp__ats__search_offers"              # public JSON APIs of the career pages (ATS) of a few companies
  "mcp__ats__get_offer_details"
  "mcp__claude_ai_Indeed__search_jobs"      # claude.ai connector (the Indeed MCP server only accepts Claude)
  "mcp__claude_ai_Indeed__get_job_details"   # only these 2 Indeed tools
)

# Always refused, even if another rule allows it (deny beats allow).
# Needed because dontAsk still runs what needs no approval: file reads in this folder, and
# read-only shell commands such as `cat` or `ls`. Without "Bash" here, the agent could run `cat .env`.
DENIED_TOOLS=(
  "Bash"
  "WebFetch"
  "WebSearch"
  "Grep"                 # not needed, and a Read deny is only "best effort" for Grep: close it
  "Read(./.env)"
  "Read(./.env.*)"
  "Read(./tests/expected_results.md)"
  "Read(./data/**)"      # only through the memory MCP server
  # dontAsk still allows reading any other file of the project (checked on 2026-10-27): close the sensitive ones.
  "Read(./.git/**)"
  "Read(./.claude/settings.local.json)"
  "Read(./.venv/**)"
  # My CV and my drafts: the offers are untrusted, and the agent can send free text to Indeed (search keywords).
  # A prompt injection could leak my phone number in a keyword: never let it read them.
  "Read(./profile/**)"
  "Read(./applications/**)"
  # In the container: my login (home folder) and the secrets in the environment of the process.
  "Read(//home/agent/**)"
  "Read(//proc/**)"
  # Without --strict-mcp-config, ALL my claude.ai connectors are loaded: refuse all but Indeed search.
  "mcp__claude_ai_Indeed__get_company_data"
  "mcp__claude_ai_Indeed__get_resume"       # my Indeed CV: never for an agent that reads untrusted offers
  "mcp__claude_ai_Google_Drive"
  "mcp__claude_ai_monday_com"
  "mcp__claude_ai_Canva"
  "mcp__claude_ai_Claude_Docs"
  "Edit(./profile/**)"
  "Edit(./applications/**)"
)

# Sonnet by default: same quality as Opus for this job, and faster.
MODEL="${MODEL:-sonnet}"

# No --strict-mcp-config here: the Indeed connector of claude.ai must be visible. Safety: dontAsk refuses
# every tool that is not in ALLOWED_TOOLS, and the other connectors are in DENIED_TOOLS.
# stream-json + --verbose: one JSON event per line, read by progress.py to show each step live.
# --tools: the only built-in tools the model even sees (no Bash at all, as in apply.sh).
OPTIONS=(-p "$PROMPT" --model "$MODEL" --permission-mode dontAsk --tools "Skill,Read,Write,Edit,Glob"
         --allowedTools "${ALLOWED_TOOLS[@]}" --disallowedTools "${DENIED_TOOLS[@]}"
         --mcp-config .mcp.json --output-format stream-json --verbose)

# Some servers read many pages, with a pause between two requests: give an MCP tool up to 10 minutes.
export MCP_TOOL_TIMEOUT=600000

mkdir -p reports
echo "▶ Mode: $MODE | Model: $MODEL | $NOW"
echo "  Each step is shown below (10 to 20 minutes in normal mode). Do not press Ctrl+C: see reports/ for the result."
# If the agent fails, still check the links of the report it may have written, then exit with its error code.
STATUS=0
JOB="search"
[ "$MODE" = "test" ] && JOB="search-test"
./scripts/agent_docker.sh "$JOB" "${OPTIONS[@]}" | .venv/bin/python scripts/progress.py || STATUS=$?

# Normal mode: check the links of the new report (no network call, exit code 1 if a link is dangerous).
# Not an agent tool: the agent itself still runs no shell command.
if [ "$MODE" = "normal" ]; then
  echo
  echo "▶ Checking the links of the newest report"
  LINKS=0
  .venv/bin/python scripts/check_links.py || LINKS=$?
  if [ "$LINKS" = "1" ]; then
    echo "⚠ DANGER link found: do not click it (see above)."
    exit 4   # pipeline.sh stops here: no email for a report with a trap
  fi
fi
exit "$STATUS"
