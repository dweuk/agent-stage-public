# Commands

All the commands of the project, in one list. Run them from the project folder. Details: `README.md`.
**Nothing here sends an email or applies to an offer**: I always send myself.

## Docker

- `claude setup-token`, then `CLAUDE_CODE_OAUTH_TOKEN=<token>` in `.env`: the simplest login for the agents. The agents run only in Docker: Docker Desktop must run.
- `./scripts/agent_docker.sh login`: the other login, in the container, needed for the Indeed connector. Copy the whole link (one long line) in the browser, then paste the code back.
- `./scripts/agent_docker.sh check`: checks Docker, the image and the login.

## Daily use

- `./scripts/search.sh`: searches offers on all the sources, scores them with your criteria, and writes the report of the 12 best in `reports/YYYY-MM-DD.md`. The offers are saved in your memory, so they never come back. About 10 minutes.
- `MODEL=opus ./scripts/search.sh`: the same search with another model (default: Sonnet).
- `./scripts/apply_all.sh`: writes the emails of every offer of the latest report, all in one file: `applications/<report name>/mails.md`. Same headings for each offer: Offre, Destinataire, Manque, À vérifier et points importants, Mail. Run it again to finish the offers that failed. When all the emails are in `mails.md`, `parts/` is deleted.
- `./scripts/apply_all.sh reports/2026-10-28.md 1 3`: the same, only for offers 1 and 3 of this report.
- `./scripts/apply.sh <offer id | company | offer text>`: a chat that writes the draft for one offer, in `applications/`. The email follows your base `profile/email-base.md`.
- `./scripts/apply.sh "$(pbpaste)"`: the same, from an offer text copied in the clipboard (for example an Indeed offer).
- `./scripts/track.sh`: a chat (in French) to record what I did: application, follow-up, interview, answer… It shows a summary and waits for your « oui ».
- `./scripts/track.sh "j'ai postulé chez Nova hier"`: the same, starting with this message.
- `./scripts/pipeline.sh --real`: the whole day in one command: search → emails of the 12 offers of the report. One file for all the offers (`reports/<name>.md`), one file for all the emails (`applications/<name>/mails.md`). Your real memory is used.

## Test the whole chain

- `./scripts/pipeline.sh`: unit tests → search → emails of all the offers of the report. A new empty test memory is used: your memory and your tracking are not touched, and the emails go to `applications/pipeline-<name>/mails.md`. The search calls the sources for real. About 30 minutes.
- `OFFERS="1 4" ./scripts/pipeline.sh`: only these offer numbers.
- `MEMORY_DB=/tmp/check/offers.db ./scripts/search.sh`: a real search only, with a test memory, in its own folder (`rm -f /tmp/check/offers.db` first to see all the offers again).

## Tests without network

- `.venv/bin/python -m pytest tests/unit`: the unit tests (report parsing, `mails.md`, keywords). No network, no Claude, never your real memory. A few seconds.
- `./scripts/search.sh test`: the agent scores the fake offers of `tests/fake_offers.json` and writes `reports/test-YYYY-MM-DD.md`. You can compare it with your own `tests/expected_results.md` (ignored by git; never give this file to the agent).
- `.venv/bin/python scripts/check_links.py [report]`: checks every link of a report before I click: OK / CHECK / DANGER (invented link, link copied from an offer, trick). Run automatically by `search.sh` and `apply_all.sh`: a DANGER stops the emails.
- `.venv/bin/python scripts/check_links.py [report] --resolve`: the same, and also follows the short Indeed links (network).
- `printf '%s\n' '{"type":"result","result":"ok"}' | .venv/bin/python scripts/progress.py`: checks the live progress display, without Claude.
- `bash -n scripts/<name>.sh`: checks the syntax of a shell script, without running it.

## Tests of one source (real network)

- `.venv/bin/python mcp/la_bonne_alternance/server.py --test`: La bonne alternance API (needs `LBA_API_KEY` in `.env`).
- `.venv/bin/python mcp/ats/server.py --test`: career pages of the companies (ATS), about 40 requests.
- `claude mcp list`: shows if each MCP server starts (`✔ Connected`).

## Tools for one step

- `.venv/bin/python scripts/offer_keywords.py <link or offer id> <folder>`: the keywords of one offer found in your CV or missing, in `<folder>/keywords.md` (run by `apply_all.sh`).
- `.venv/bin/python scripts/applications_index.py mails <report.md> <folder>`: writes `mails.md` again (run by `apply_all.sh`).
- `.venv/bin/python scripts/applications_index.py list <report.md> <folder>`: the offers of a report and their state (`todo`, `done`, `applied`).
- `.venv/bin/python scripts/benchmark_llm.py [offer.md] [--models m1 m2…]`: the same draft written by several models (Haiku, Sonnet, or local Ollama models), to compare them. Output: `applications/test-llm/`.

## Useful variables (before a command)

- `MODEL=opus`: another model for `search.sh`, `apply.sh`, `apply_all.sh`, `pipeline.sh`. `MODEL=ollama:<model>` for a local model (`apply.sh` only, not tested yet).
- `MEMORY_DB=/tmp/x/offers.db`: another memory file, in its own folder, so your real memory is not touched.
- `OUT_DIR=applications/test`: another folder for the drafts (must be in `applications/`).
- `OFFERS="1 2"`: only these offer numbers for `pipeline.sh` (default: all).
