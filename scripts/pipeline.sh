#!/bin/bash
# The whole day in one command: unit tests → search → one email draft per offer of the report.
# Result: 1 file for all the offers (reports/<name>.md) and 1 file for all the emails (<folder>/mails.md).
# Nothing is ever sent: I check each email and send it myself.
#
# Usage:
#   ./scripts/pipeline.sh                  → trial: test memory, emails for all the offers of the report (12)
#   ./scripts/pipeline.sh --real           → my real memory (the offers found are saved: daily use)
#   OFFERS="1 4" ./scripts/pipeline.sh     → only these offer numbers of the report
#
# The agents run in Docker (scripts/agent_docker.sh): Docker must run, and I must have logged in once.
# Trial mode: MEMORY_DB is a new empty file (PIPELINE_DB, default /tmp/agent-stage-pipeline/offers.db), so my memory
# and my tracking are never touched, and the drafts go to applications/pipeline-<report name>/.
# The search really calls the sources (Indeed, La bonne alternance, ATS).
# Env: MODEL is passed to search.sh and apply_all.sh.

set -euo pipefail
cd "$(dirname "$0")/.."  # the project root (this script lives in scripts/)

./scripts/agent_docker.sh check

REAL=0
for ARG in "$@"; do
  case "$ARG" in
    --real)  REAL=1 ;;
    *) echo "Usage: ./scripts/pipeline.sh [--real]" >&2; exit 1 ;;
  esac
done
OFFERS="${OFFERS:-all}"
if [[ ! "$OFFERS" =~ ^(all|[0-9]+( [0-9]+)*)$ ]]; then
  echo "OFFERS must be numbers separated by spaces, or \"all\"." >&2
  exit 1
fi
[ "$OFFERS" = "all" ] && OFFERS=""

if [ "$REAL" = "0" ]; then
  export MEMORY_DB="${PIPELINE_DB:-/tmp/agent-stage-pipeline/offers.db}"
  mkdir -p "$(dirname "$MEMORY_DB")"
  rm -f "$MEMORY_DB"   # a new memory: every offer is new, as for a first run
  echo "▶ Trial mode: test memory $MEMORY_DB (my memory and my tracking are not touched)."
else
  echo "▶ Real mode: the offers found are saved in my memory."
fi
echo "  The search calls the sources for real (10 to 20 minutes), then emails for offers: ${OFFERS:-all}."
read -r -p "Continue? [y/N] " ANSWER
[ "$ANSWER" = "y" ] || { echo "Nothing done."; exit 0; }

STEP_START=$SECONDS
step() { echo; echo "━━━ $1 ($(( (SECONDS - STEP_START) / 60 )) min since the start)"; }

step "1/3 Unit tests"
.venv/bin/python -m pytest tests/unit -q

step "2/3 Search"
MARKER="$(mktemp)"
trap 'rm -f "$MARKER"' EXIT
# search.sh exits with the error of the agent: go on only if it wrote a new report.
SEARCH=0
./scripts/search.sh || SEARCH=$?
if [ "$SEARCH" = "4" ]; then
  echo "❌ DANGER in the new report: stop, no email. Read it as plain text, not in a preview." >&2
  exit 4
fi
[ "$SEARCH" = "0" ] || echo "⚠ The search ended with an error: looking for its report anyway."
# The newest report written during this run (test-*.md are fake offers).
REPORT="$(find reports -maxdepth 1 -name '*.md' ! -name 'test-*' -newer "$MARKER" -print0 \
          | xargs -0 ls -t 2>/dev/null | head -1 || true)"
if [ -z "$REPORT" ]; then
  echo "❌ No new report in reports/: stop. See the lines above." >&2
  exit 1
fi
echo "Report: $REPORT"

step "3/3 Emails"
NAME="$(basename "$REPORT" .md)"
if [ "$REAL" = "0" ]; then
  export OUT_DIR="applications/pipeline-$NAME"
else
  export OUT_DIR="applications/$NAME"
fi
# $OFFERS is not quoted on purpose: one argument per offer number (checked by the regex above).
# shellcheck disable=SC2086
./scripts/apply_all.sh "$REPORT" $OFFERS

step "Done"
echo "All the offers: $REPORT"
echo "All the emails: $OUT_DIR/mails.md"
echo "Nothing was sent. Check each email, then send it yourself."
