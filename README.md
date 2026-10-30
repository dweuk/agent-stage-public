# Internship / work-study search agent

An agent that **searches** internship (stage) and work-study (alternance) offers in France, **scores** them with your criteria, and writes a **report in French** of the 12 best. It never applies, never sends a message, never creates an account. Your places, jobs and companies are never in the code: they are in files that git ignores (see "Your own settings").

The main interest of the project is its safety: an agent that reads untrusted text from the web must not be able to leak your CV or trap your report. See "Data and safety".

- The how (components, data flow, file tree): `docs/ARCHITECTURE.md`
- Every command in one list: `docs/COMMANDS.md`
- Rules for the agent and for development: `CLAUDE.md`

## Usage and terms

- **Personal use only.** This project helps one person search internships for themselves. It is not a service, and it must not be used to collect offers or personal data at scale.
- **No sending.** The agent never applies, never sends an email or a message, and never fills in a form. The emails are only drafts in one local file: you check and send each email yourself.
- **Personal data.** Your CV, your criteria, your settings, the offers seen, the reports and the drafts stay on your computer (`profile/`, `data/`, `reports/`, `applications/`, `config/search.json`, `config/ats_keywords.txt`, `criteria.md` and `searches.md` are ignored by git). Never commit them, and never publish the contact details of recruiters found in offers (GDPR, the General Data Protection Regulation).
- **AI output.** The scores, reports and drafts are written by an LLM (large language model): they can be wrong. Check each offer and each draft before you use it.
- **Licence.** MIT: see `LICENSE`.

## How it works

```
./scripts/search.sh → claude -p (Sonnet) → skill search-offers
   → la-bonne-alternance.search_offers()      short list of offers (+ the other sources, Indeed: 20 calls)
   → memory.filter_already_seen(ids)          only the new ones
   → memory.find_reposts(offers)              the same offer under another id: not analysed again
   → get_offer_details(ids)                   full offers, 10 per call
   → score each offer (criteria.md)           → reports/YYYY-MM-DD.md
   → memory.save_evaluations(...)             so they never come back
```

The agent is Claude Code in non-interactive mode. The tools are MCP (Model Context Protocol) servers in Python, in `mcp/`.

## Setup (first time)

1. **Python environment** (Python 3.13):
   ```
   uv venv .venv --python 3.13
   uv pip install --python .venv/bin/python --require-hashes -r requirements.lock
   ```
2. **Docker**: the agents run only in Docker, and the container cannot use the login of the Mac (it is in the macOS Keychain). Start Docker Desktop, then choose one way to log in:
   - **Token (simplest)**: run `claude setup-token` on the Mac, then add `CLAUDE_CODE_OAUTH_TOKEN=<token>` to `.env`. The claude.ai connectors are not loaded with it: the script prints a warning, and the search says that Indeed is not available and uses the other sources.
   - **Login in the container** (needed for the Indeed connector): `./scripts/agent_docker.sh login`, open the link in your browser, then paste the code back in the terminal. The link is one long line: copy all of it. The login stays in the Docker volume `agent-stage-claude` (`docker volume rm agent-stage-claude` removes it), and it is used first if both exist.

   The first run builds the image.
   Each container sees only the files of its job (`config/search.json` only for the search and application jobs): never `.env`, `.git`, `tests/expected_results.md` or `cv.pdf`; the search agent has no CV and no draft; an application agent sees only the folder of its offer. Read-only system, no Linux capability, non-root user. **Limit**: the network stays open, because the servers need it to read the offers.
3. **Secrets**: create a `.env` file at the root of the project (it is in `.gitignore`, never share it):
   ```
   LBA_API_KEY=...
   ```
   - `LBA_API_KEY`: create an account on https://api.apprentissage.beta.gouv.fr, then "Get an API key" in the profile. Choose a **production** key: a sandbox key returns test data, not real offers (the server stops if it sees test data).
4. <a id="your-own-settings"></a>**Your own settings** (ignored by git, so your wishes stay private; the repository only has examples):
   ```
   cp .claude/skills/search-offers/criteria.example.md .claude/skills/search-offers/criteria.md
   cp .claude/skills/search-offers/searches.example.md .claude/skills/search-offers/searches.md
   cp config/search.example.json config/search.json
   cp config/ats_keywords.example.txt config/ats_keywords.txt
   ```
   Then replace every `<…>` of the first 2 files and every value of `config/search.json` (the places, jobs and company in it are only examples), and write the keywords of your field in `config/ats_keywords.txt`.
5. **Check the sources**
   ```
   .venv/bin/python mcp/la_bonne_alternance/server.py --test
   .venv/bin/python mcp/ats/server.py --test
   ```
   Expected: `✅ N calls, … offers (last 31 days) …` or `✅ N offers out of …`, a few offers, then `✅ Details of the 1st offer: …`.

## Daily use

| Command | What it does |
|---|---|
| `./scripts/search.sh` | Real search. Writes `reports/YYYY-MM-DD.md` (`-2`, `-3`… if the file exists). Takes about 10 minutes; each step is shown live (see below). Exit code 4 if the report contains a DANGER link |
| `./scripts/search.sh test` | Test mode: the fake offers of `tests/fake_offers.json`, no memory. Writes `reports/test-YYYY-MM-DD.md` |
| `MODEL=opus ./scripts/search.sh` | Same, with another model (default: Sonnet) |
| `MEMORY_DB=/tmp/check/offers.db ./scripts/search.sh` | Trial run: a real search, but your memory is not touched (see "Trial run" below) |
| `./scripts/track.sh` | Chat (in French) to record your applications, follow-ups, interviews… It shows a summary and waits for your « oui » before writing |
| `./scripts/track.sh "j'ai postulé chez Nova hier"` | Same, starting with this message |
| `./scripts/apply.sh <offer id, company or offer text>` | Writes a **draft** (never sent) in one file of `applications/`, with always the same headings: Offre, Destinataire, Manque, À vérifier et points importants, Mail. Needs `profile/cv.md` (your CV as plain text) and `profile/email-base.md` (the base of your emails: the agent keeps its fixed text word for word and fills in its `{...}` parts). It uses only skills written in your CV. The Indeed connector is loaded only when the whole request is an `indeed:` id or an Indeed link, never because the word is in a text. After the run, the script checks every new file of the output folder: a file that is not `.md`, an image, an HTML tag or attribute that loads something, a `//host` link or a URL that is not in your CV or your email base gives a ⚠ DANGER message (exit code 3): then read the draft as plain text, never in a Markdown preview |
| `./scripts/apply_all.sh [report.md] [numbers...]` | Same, for all the offers of a report (default: the latest, not `test-*`), or only the given offer numbers. It first runs `check_links.py`: a report with a DANGER link gives no email (exit code 4). Output: **`applications/<report name>/mails.md`** (in French), the only file to open. The title, company and link of each offer go in `parts/NN-company/offer-data.md`, which the agent reads as data: they never enter its prompt. **Run it again to finish**: offers with a valid draft are skipped, failed ones are tried again, and offers with an application in your tracking are skipped. Working files in `parts/` are deleted at the end when every offer has its email in `mails.md`. To start again, delete `mails.md`. Before the agent, `scripts/offer_keywords.py` writes `keywords.md`: the keywords of the offer found in or missing from `profile/cv.md`, computed by code from the list `config/ats_keywords.txt` |
| `./scripts/pipeline.sh [--real]` | The whole day in one command: unit tests → `search.sh` → `apply_all.sh` on **all the offers** of the new report (`OFFERS="1 4"` for only some of them). It stops if the report contains a DANGER link. Asks before starting. Default = **trial**: a new empty test memory (`PIPELINE_DB`, default `/tmp/agent-stage-pipeline/offers.db`), emails in `applications/pipeline-<report name>/`, your memory and tracking untouched. `--real`: your real memory and `applications/<report name>/`. Nothing is ever sent |

An offer is shown **only once**: after a run, it is saved in the memory.

**Live progress**: `scripts/search.sh` runs `claude -p` with `--output-format stream-json --verbose`, and `scripts/progress.py` turns each event into one line: time since the start, MCP servers connected or not, each tool call (`→`) and its result (`✅` with the number of offers, `❌` error, `⏳` refused by the Indeed call limit), the step lines of the agent (in French), a `… still working` line every 30 seconds without news, then an Indeed summary and the last message of the agent. Offer texts are never printed (they are untrusted: control characters are removed from everything).

### Trial run (without touching your memory)

```
MEMORY_DB=/tmp/check/offers.db ./scripts/search.sh
```

- `MEMORY_DB=...` before the command sets an environment variable for this command only. The memory server then uses this file instead of your real memory `data/offers.db`. It must be in its own folder: this folder is mounted in the container.
- **When to use it**: the first time, or after a change of sources, keywords or skill. The offers found are saved in the test file only, so your next real `./scripts/search.sh` still shows them.
- **What is real**: everything else. The sources are really called, and the report is written in `reports/` like a normal report.
- **Start from zero**: `rm -f /tmp/check/offers.db` before the run.

## Sources

| Source | Offers | Server |
|---|---|---|
| La bonne alternance (official public API, with your own key) | **Work-study only**: La bonne alternance and its partners | `mcp/la_bonne_alternance/server.py` |
| Indeed (claude.ai connector) | **Internships and work-study** (about 10 offers per search, 20 searches; the contract label is sometimes wrong) | the connector of claude.ai, no server in this project |
| ATS career pages (official public APIs) | **Internships and work-study** of the companies of `config/search.json` (SmartRecruiters, Greenhouse, Lever, Ashby) | `mcp/ats/server.py` |

**Other sources.** Ways to get the offers of LinkedIn, HelloWork and France Travail exist, but I cannot provide them in this repository. It only contains sources with an official API or connector.

### How the ATS career pages work
- Many companies publish their offers with an ATS (applicant tracking system, the software of their career page). SmartRecruiters, Greenhouse, Lever and Ashby give an **official public JSON API** per company: no HTML, no account. Idea taken from [freehire](https://github.com/strelov1/freehire) (`scripts/ats_boards.py`, MIT licence).
- The companies are in `boards` of `config/search.json`: you choose them.
- **Filters of the code**: internship or work-study only, title close to your jobs (`job_title_patterns`), your zone (`zone_departments`, or a town of `zone_cities`), last 31 days, no senior title.
- **To add a company**: open its career page; if a link looks like `jobs.smartrecruiters.com/<board>/…`, `job-boards.greenhouse.io/<board>/…`, `jobs.lever.co/<board>/…` or `jobs.ashbyhq.com/<board>/…`, add one line to `boards`, then run the test of the server.
- One request at a time, 1 second of pause, 120 requests at most per run. The link of each offer is built from its id.

### Reposts and ghost jobs
The same offer often comes back with another id: on another source, or republished by the company. After `filter_already_seen`, the agent calls `memory.find_reposts`: the code compares company + title + area (the `memory` section of `config/search.json`, else the department) with every offer already in memory. A repost is not analysed again (fewer tokens, fewer requests): it is listed in the appendix « Republications » of the report, with the old score, and saved with the status `repost`. If the offer was first seen more than 60 days ago, the report says « offre fantôme possible » (an offer that nobody really recruits for).

### How Indeed works
`./scripts/search.sh` uses **your claude.ai connector**:
- It must be connected in claude.ai (Settings → Connectors → Indeed), with the same account as the login of the agents.
- `scripts/search.sh` has no `--strict-mcp-config`, so all your claude.ai connectors are visible to the agent. Only `search_jobs` and `get_job_details` of Indeed are allowed; the other connectors and `get_company_data` and `get_resume` are in `DENIED_TOOLS`. If you add a new connector, add it to `DENIED_TOOLS`.
- There is no code between Indeed and the agent: the filters (zone, 31 days) and the stable `id` are done by the agent, following "Indeed procedure" in the skill. The Indeed ids and links change at every call, so the `id` is built from company + title + date.
- **Searches**: 20 per run, in 5 groups of 4 (place and keywords). To change them: the « Indeed » section of `searches.md`.
- **Call limit**: Indeed refuses calls when it gets too many in one minute (`-32429 Rate limit exceeded`). The agent respects it: it repeats each refused call **once**, at the end (step 3c of the skill), and the report names each lost search. If many calls are refused, remove keywords.

## Change the search

| What | Where |
|---|---|
| Scoring grid, eliminating criteria | `.claude/skills/search-offers/criteria.md` |
| Bonus for « convention de stage » (+1,5 point) and for « stage ou alternance » (+2 points) | `mcp/score_bonus.py` (`CONVENTION_BONUS`, `MIXED_CONTRACT_BONUS`, the regexes). Not for Indeed (no code of this project reads its texts) |
| Number of offers in the report, minimums by place | `criteria.md`, step C |
| Indeed keywords and places | `.claude/skills/search-offers/searches.md` |
| Jobs of La bonne alternance (ROME codes) | `romes` in `config/search.json` |
| Places, ATS companies and filters | `config/search.json` (one section per server) |
| Report format | `.claude/skills/search-offers/report-template.md` |

**ROME codes** (French directory of jobs, version 4.0): La bonne alternance has no keyword search, only ROME codes. To find the code of a job title, use the France Travail ROME directory or the job search of the La bonne alternance website. The ROME code of the example file is only an example: check yours.

After any change to the criteria, run `./scripts/search.sh test` and read the report. You can write the scores you expect in `tests/expected_results.md` (ignored by git). ⚠️ Never give this file to the agent.

## Tests

| Test | Command |
|---|---|
| Unit tests (no network, no Claude, no Docker, never the real memory) | `.venv/bin/python -m pytest tests/unit`: report parsing, what each container sees, traps in links, Indeed connector rule, offer fields kept out of the prompt, stop on DANGER, keyword matching |
| The agent and the criteria | `./scripts/search.sh test` (5 fake offers, including one prompt injection) |
| La bonne alternance, real API | `.venv/bin/python mcp/la_bonne_alternance/server.py --test` |
| ATS career pages, real APIs (about 40 requests) | `.venv/bin/python mcp/ats/server.py --test` |
| The whole chain, without touching your memory | `MEMORY_DB=/tmp/check/offers.db ./scripts/search.sh` (see "Trial run") |
| Links of a report (traps) | `.venv/bin/python scripts/check_links.py [report] [--resolve]`: run by hand, or automatically by `search.sh` and `apply_all.sh`. OK / CHECK / DANGER; exit code 1 if DANGER, 2 if there is no report. A link that no server returned (not in `data/returned_urls.jsonl`, written by `mcp/returned_urls.py`) is DANGER: invented, or copied from an offer (prompt injection). Indeed links skip this check (no code of this project sees them). The text is checked too: a Markdown image, an HTML tag or attribute that loads something (`<details>` is allowed), a `javascript:` / `data:` link or a `//host` link is DANGER. Without `--resolve` no network call |
| Benchmark of the application draft: several models, same short context | `.venv/bin/python scripts/benchmark_llm.py [offer.md] [--models m1 m2…]`. Each model gets the same 2 messages only: a short system prompt + your CV + one offer (default: the fake offer `tests/fake_offer_apply.md`). No tool, no skill, no CLAUDE.md. Default models: haiku and sonnet through `claude -p`; add `ollama:<model>` for a local model (`ollama serve` must run). Output: `applications/test-llm/` |
| Live progress display, without Claude | `printf '%s\n' '{"type":"result","result":"ok"}' \| .venv/bin/python scripts/progress.py` |

## Data and safety

- **Memory**: `data/offers.db` (SQLite). Nothing is ever deleted or overwritten. A copy is made in `data/backups/` each time the memory server starts, if the database changed since the newest copy (the last 30 are kept).
- **Permissions** (details: `docs/ARCHITECTURE.md` §3.4):
  - `scripts/search.sh` and `scripts/track.sh` allow only the tools they need (`--allowedTools`) and refuse the rest (`--disallowedTools`): no shell, no web, no `.env`, no `data/`, no `tests/expected_results.md`, no `profile/` and no `applications/` (your CV must never reach the search agent: it reads untrusted offers and sends keywords to Indeed), no writing outside `reports/`. The search agent cannot touch your tracking. `scripts/apply.sh` can read `profile/` and write only in its `OUT_DIR` (`applications/` by default); it cannot write in the tracking.
  - The deny rules are needed: `--permission-mode dontAsk` still lets file reads in the project folder and read-only shell commands (`cat`, `ls`…) run without asking.
  - `.claude/settings.json` (shared with the project) denies reading and editing `.env`, and editing `data/`, in **every** session, including when you work on the code with Claude.
  - Never remove these rules. To allow something new, add an allow rule for exactly that path.
- **Supply chain**: the Docker base images are pinned by digest, the Python packages by hash (`requirements.lock`), and Claude Code by version.
- **MCP servers**:
  - The ids sent by the agent are checked with a regular expression before they go into a URL. An id like `../x` or `x?y=1` gets an `invalid id` error and never reaches the API.
  - When an API says "too many requests" (429) or fails (5xx): 4 tries at most, 15 seconds between two tries. The `Retry-After` header is ignored, so a huge value cannot block the search.
  - Error messages never contain the API answer body (no risk of showing a secret).
  - `ats` builds the link of each offer from its id. The links of `la-bonne-alternance` come from its API: `check_links.py` checks them.
  - The agent never visits a website itself (no `WebFetch`, no shell). Only the servers read APIs, and their code fixes which pages and how many requests.
