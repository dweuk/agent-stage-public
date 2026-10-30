#!/bin/bash
# Write the application emails for ALL the offers of a report (default: the latest one), and join them
# in one file. Nothing is sent: I check each email and send it myself.
#
# Usage:
#   ./scripts/apply_all.sh                        → the latest report of reports/
#   ./scripts/apply_all.sh reports/2026-10-27.md  → a given report
#   ./scripts/apply_all.sh reports/x.md 1 3 5     → only the offers number 1, 3 and 5 of the report
#
# Output: applications/<report name>/ (ignored by git):
#   mails.md      in French: ALL the emails, with the same headings; then DANGER, failed, already sent
#                 (rewritten after each offer). This is the only file I need to open.
#   parts/NN-company/  working files of offer number NN: its draft, keywords.md (scripts/offer_keywords.py) and
#                 offer-data.md (title, company and link of the report: data for the agent, never in its prompt).
#                 Deleted at the end if all is in mails.md; kept if an offer is failed, not done or DANGER.
#   status.tsv   result of each run of an offer (ok, danger, failed), read by applications_index.py
#   timings.txt   time of each offer
#
# Run it again to finish: offers with a valid draft are skipped, failed ones are tried again.
# Offers with an application in my tracking (./scripts/track.sh) are skipped too.
# To redo one offer: delete its folder in parts/, then run again. Once parts/ is deleted: use apply.sh for one
# offer, or delete mails.md to start again.
# Env: MODEL is passed to apply.sh (see there). OUT_DIR replaces applications/<report name>.
# One run of scripts/apply.sh per offer (BATCH=1: no chat).

set -euo pipefail
cd "$(dirname "$0")/.."  # the project root (this script lives in scripts/)

# `|| true`: with no report, `ls` fails, and pipefail + set -e would stop here without the message below.
# Test reports (test-*.md) are skipped by default: they hold fake offers.
REPORT="${1:-$(ls -t reports/*.md 2>/dev/null | grep -v '^reports/test-' | head -1 || true)}"
if [ -z "$REPORT" ] || [ ! -f "$REPORT" ]; then
  echo "No report found. Usage: ./scripts/apply_all.sh [report.md] [offer numbers...]" >&2
  exit 1
fi
shift || true
ONLY=" $* "

# Same check as in apply.sh, done here too: status.tsv, timings.txt and mails.md are written by this script.
BASE="${OUT_DIR:-applications/$(basename "$REPORT" .md)}"
if [[ ! "$BASE" =~ ^applications(/[A-Za-z0-9_][A-Za-z0-9._-]*)*$ ]]; then
  echo "Output folder $BASE: must be applications or a sub-folder of applications/ (letters, digits, . _ -, not starting with . or -)." >&2
  exit 1
fi
mkdir -p "$BASE"

# No parts/ next to mails.md: this report is finished, and mails.md is the only copy of its emails.
if [ -f "$BASE/mails.md" ] && [ ! -d "$BASE/parts" ]; then
  echo "$BASE/mails.md is already finished: nothing to do. To start again, delete it first."
  exit 0
fi

# No email for a report with a trap. Exit code 1 of check_links.py = DANGER (no network call).
LINKS=0
.venv/bin/python scripts/check_links.py "$REPORT" || LINKS=$?
if [ "$LINKS" = "1" ]; then
  echo "⚠ DANGER in $REPORT (see above): no email written. Read the report as plain text, and remove the offer." >&2
  exit 4
fi

INDEX=(.venv/bin/python scripts/applications_index.py)

# One line per offer: num, title, company, link, folder, state, separated by \x1f (see applications_index.py).
OFFERS="$("${INDEX[@]}" list "$REPORT" "$BASE")"
if [ -z "$OFFERS" ]; then
  echo "No offer found in $REPORT" >&2
  exit 1
fi

# Ctrl+C: `claude` catches it and exits with an error, so without this trap the loop would go on with the
# next offer. Bash runs the trap when the current offer stops: mails.md is written, then the whole run ends.
trap 'echo; echo "Stopped (Ctrl+C). Run the same command again to finish." >&2; "${INDEX[@]}" mails "$REPORT" "$BASE"; exit 130' INT

DONE=0
FAILED=0
SKIPPED=0
# IFS=\x1f, not a tab: a tab is white space for `read`, so an empty field would move the next ones.
while IFS=$'\x1f' read -r NUM TITLE COMPANY LINK FOLDER STATE; do
  if [ -n "${ONLY// /}" ] && [[ "$ONLY" != *" $NUM "* ]]; then continue; fi
  case "$STATE" in
    applied) echo "--- Offer $NUM ($COMPANY): already applied (tracking), skipped."; SKIPPED=$((SKIPPED + 1)); continue ;;
    done)    echo "--- Offer $NUM ($COMPANY): draft already in $BASE/$FOLDER, skipped."; SKIPPED=$((SKIPPED + 1)); continue ;;
  esac
  echo "=== Offer $NUM: $TITLE ($COMPANY) → $BASE/$FOLDER"
  START=$SECONDS
  # Keywords of the offer found in / missing from my CV, computed by code (keywords.md in the folder). Only names
  # of config/ats_keywords.txt are printed, never a word of the offer, so they can go into the prompt.
  KEYWORDS="$(.venv/bin/python scripts/offer_keywords.py "$LINK" "$BASE/$FOLDER" < /dev/null || true)"
  # The fields of the report come from offer texts: they go in a file that the agent reads as data, never in its
  # prompt (the keyword lines hold only names of my list). OFFER_LINK is only for the Indeed check of apply.sh.
  mkdir -p "$BASE/$FOLDER"
  printf 'Title: %s\nCompany: %s\nLink: %s\n' "$TITLE" "$COMPANY" "$LINK" > "$BASE/$FOLDER/offer-data.md"
  # < /dev/null: else `claude -p` reads the stdin of this loop (the other offers) and adds it to its prompt.
  # Exit code 3 = the draft was written, but apply.sh found an image, HTML or an unknown URL in them.
  RESULT="ok"
  CODE=0
  OUT_DIR="$BASE/$FOLDER" BATCH=1 OFFER_LINK="$LINK" ./scripts/apply.sh \
    "$(printf 'Offer data file: %s\n%s' "$BASE/$FOLDER/offer-data.md" "$KEYWORDS")" < /dev/null || CODE=$?
  if [ "$CODE" = "3" ]; then
    RESULT="danger"
  elif [ "$CODE" != "0" ]; then
    RESULT="failed"
  fi
  if [ "$RESULT" != "ok" ]; then
    FAILED=$((FAILED + 1))
    echo "!!! Offer $NUM: $RESULT (see above), I go on with the next one." >&2
  fi
  printf '%s\t%s\t%s\t%s\n' "$NUM" "$RESULT" "$(date '+%Y-%m-%d %H:%M')" "${MODEL:-sonnet}" >> "$BASE/status.tsv"
  echo "offer $NUM: $((SECONDS - START)) s (${MODEL:-sonnet}) $RESULT" >> "$BASE/timings.txt"
  DONE=$((DONE + 1))
  "${INDEX[@]}" mails "$REPORT" "$BASE" > /dev/null  # up to date even if the run stops later
done <<< "$OFFERS"

echo "Done: $DONE offer(s) run, $FAILED failed or with DANGER, $SKIPPED skipped."
"${INDEX[@]}" mails "$REPORT" "$BASE"
"${INDEX[@]}" clean "$REPORT" "$BASE"
echo "Open $BASE/mails.md: check each email, then send it yourself."
