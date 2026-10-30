# Architecture: internship / work-study search agent

> This file describes the how. How to install and use it: `README.md`.

---

## 1. Principle

The agent runs in **Claude Code** (non-interactive mode `claude -p`).
Claude Code already provides the agent loop (think → call a tool → read the result).
I provide:
- the **instructions** (`CLAUDE.md`)
- the **method** (skills)
- the **tools** (your MCP servers in Python)
- the **launchers** (`scripts/search.sh` for the search, `scripts/track.sh` for your tracking, `scripts/apply.sh` for application drafts)

## 2. Who does what: the code or the LLM?

**Rule**: everything that is certain, repetitive or checkable → **the code**. Everything that needs judgement → **the LLM**.

| Step | Who | Why |
|---|---|---|
| Call the sources (La bonne alternance API, ATS APIs) | Code (MCP) | Technical, always the same |
| Loop over ROME codes × places | Code (MCP) | Avoids dozens of tool calls by the LLM |
| Put the offers in the same format (see §4) | Code (MCP) | The LLM always gets the same structure, whatever the source |
| Remove offers already seen | Code (memory MCP) | Must be 100% reliable |
| Simple eliminating criteria: freelance / temporary contract, place outside the zone | Code, if the information is in the fields | Reliable and free. Fewer offers sent to the LLM = fewer tokens |
| Eliminating criteria "hidden" in the text (e.g. "full remote" in the description) | LLM | Needs to read and understand the text |
| Estimate the share of coding, human contact, learning | LLM | Judgement |
| Score /10 and justify | LLM | Judgement |
| Sort, keep the top 12 ≥ 4/10 (with the minimums by place of `criteria.md`) | LLM (or code later) | Simple, but depends on the LLM's scores |
| Write the Markdown report | LLM (Claude Code's `Write` tool) | Formatting and explanations |
| Save the evaluated offers (id, score, date) | Code (memory MCP) | Reliable history |

## 3. Components

### 3.1 Instructions: `CLAUDE.md`
Two parts:
- **Agent rules**: the agent's role and its **prohibitions** (never apply, send a message, create an account…).
- **Development rules**: for Claude when you work on the code with it. **Code and LLM instructions always in English, never in French.**

Loaded automatically by Claude Code each time it starts in this folder.

### 3.2 Method: the skills
```
.claude/skills/
├── search-offers/
│   ├── SKILL.md            ← the steps to follow (the flow of §5)
│   ├── criteria.md         ← short version of the criteria, written for the agent
│   └── report-template.md  ← the exact format of the report
└── tracking/SKILL.md       ← how to record and look up your tracking
```
- `criteria.md` = the scoring grid + the eliminating criteria, written by the user from `criteria.example.md`.
- **Language**: all files, code and LLM instructions are in **English**. The **reports** and the **answers to me** are in **French**.
- **Settings**: `config/search.json` (places, jobs, companies, one section per server, read by `mcp/search_config.py`) and `config/ats_keywords.txt`. Both are ignored by git: the code holds no personal value. Templates: `*.example.*`.

### 3.3 Tools: MCP servers (Python)
Three servers of this project, plus an official connector:

| Server | Tools | Role |
|---|---|---|
| `memory` (✅) | `filter_already_seen(ids)` → ids never seen | Remove duplicates (search) |
| | `find_reposts(offers)` → the new offers already in memory under another id | Same company + same title + same area (`offer_key`, `area_of`): the same offer on another source, or republished. The agent does not analyse them again (saved as `repost`). `possible_ghost` if first seen more than 60 days ago (`GHOST_DAYS`). Idea from freehire (dedup on a stable key, ghost job signal) (search) |
| | `save_evaluations(evaluations)` | Save id, score, reason, date in SQLite. An offer already saved is not overwritten (search) |
| | `add_offer(title, company, url, source, text)` | An offer I found myself → id `source:N` (tracking) |
| | `add_tracking(type, text, company, offer_id, date)` | An action on your side: application, follow_up, interview, answer, rejection, dropped, note (tracking) |
| | `find(text)` / `history(limit)` | Read the offers and your tracking (tracking) |
| `la-bonne-alternance` (✅) | `search_offers(published_since_days=31)` → **short** list + `removed_by_code` + `old_or_closed_skipped` + `errors` | **Work-study only.** No keywords: the API searches by **ROME codes** (French directory of jobs, version 4.0). The codes and the places (GPS circles) are **in `config/search.json`**. The `departements` filter of the API found half as many offers. The code removes the postal codes outside the `departments` of a place (`E3_LOCATION`, in `removed_by_code`). One call per place with all the codes; if a call reaches the API limit (150 offers per source), it is redone with one code at a time. At most 50 calls per minute (the API allows 60). Removes closed, expired and too old offers |
| | `get_offer_details(ids)` → full offers in the §4 format | At most 10 ids per call. Reads the offers kept in memory by the search |
| `ats` (✅ public JSON APIs) | `search_offers(published_since_days=31)` → **short** list + `skipped_not_internship` + `skipped_by_title` + `skipped_outside_zone` + `old_skipped` + `errors` | **Internships and work-study.** Career pages of the companies of `boards` in `config/search.json` (SmartRecruiters, Greenhouse, Ashby, Lever). These ATS (applicant tracking systems) give an official public API per company: no HTML, no account. The code keeps only internship / work-study titles (or the SmartRecruiters "internship" level), titles of `job_title_patterns`, and the zone (`zone_departments`, or a town of `zone_cities`). One call at a time, 1 s of pause, 120 requests per run at most. Idea from freehire (`scripts/ats_boards.py`) |
| | `get_offer_details(ids)` → full offers in the §4 format | At most 5 ids per call, 40 detail requests per run. Id checked (`ID_PATTERN`, and the board must be in `BOARDS`). Works without a search in the same run (for `apply.sh`). The `url` is built from the id |
| Indeed (**claude.ai connector**, not a server of this project) | `search_jobs(search, location, country_code, job_type)` → markdown list, ~10 offers, no description; `get_job_details(job_id)` | **Internships and work-study.** The official server only accepts the Claude connector (`403 Client not allowed` for a home-made client): no proxy. `scripts/search.sh` allows only these 2 tools; `get_company_data`, `get_resume` and the other connectors are denied. No code in the middle: the agent applies the zone / date filters and builds the id `indeed:<company>\|<title>\|<date>` (the Indeed ids and short links change at every call). 20 searches in 5 groups of 4 (`searches.md`), spread between the slow calls of the other servers; a call refused by the Indeed call limit (`-32429`) is repeated once at the end (step 3c of the skill) |

**Why a short list, then the details**: a full offer is about 1,000 tokens. With hundreds of offers, the agent's context would be full. The agent first gets a short list, removes the offers already seen, then asks for the details of the new ones only (80 at most per run: the others will come back next time).




**Safety of the MCP servers**:
- **The ids are checked** with a regular expression before they go into a URL (`LBA_ID_PATTERN`: 24 hexadecimal characters; `ID_PATTERN` of `ats`, and the board must be in `BOARDS`). Why: the ids come from the LLM, and the LLM reads offer texts written by anyone. Without the check, an id like `../../x` or `x?y=1` calls another route of the API, with your token. Such an id gets `invalid id` and never reaches the API.
- **Retries**: on 429 (too many requests) or 5xx, 4 tries at most, 15 seconds between two tries (`MAX_ATTEMPTS`, `RETRY_WAIT`). The `Retry-After` header is ignored: a huge value would block the whole search.
- **No secret in the errors**: the error messages never contain the body of the API answer.
- **Links built by the code** (`ats`): the `url` of an offer is made from its id, never copied from the offer. The links of `la-bonne-alternance` come from its API: `scripts/check_links.py` checks them.

**API key of La bonne alternance**: `LBA_API_KEY` in `.env`. It must be a **production** key: a sandbox key returns test data (the server stops with an error if it sees it).

**Why `memory` is a separate server**: it works for **all** sources. The sources do not need to know what was already seen.

**Never lose anything** (`memory` server):
- no tool deletes or modifies a row. To fix the tracking, add a `note` row;
- each time it starts, the server copies the database into `data/backups/` if it changed since the newest copy (the last 30 copies are kept; `apply.sh` starts it once per offer, so identical copies would else push the old ones out);
- each call is one transaction: everything is written, or nothing;
- the `MEMORY_DB` variable lets the tests use another database.

**Separation of rights**: from `memory`, `scripts/search.sh` only allows `filter_already_seen`, `find_reposts` and `save_evaluations`. `scripts/track.sh` only allows the 4 tracking tools. So the search agent cannot touch your tracking.

### 3.4 Permissions: allow, deny, and the project settings
In `claude -p` mode, nobody is there to answer "yes" to a permission request (`--permission-mode dontAsk`).

**Allow** (`--allowedTools` in the launchers): only what the agent needs.
- `scripts/search.sh`: the skill, `Read` of `.claude/skills/search-offers/**` and `tests/fake_offers.json`, `Glob`, `Edit(./reports/**)`, the search tools of the MCP servers. `--tools "Skill,Read,Write,Edit,Glob"`: the model sees no other built-in tool.
- `scripts/track.sh`: the skill and the 4 tracking tools.

**⚠️ Allow is not enough.** `dontAsk` only refuses what *needs approval*. Two things need no approval, so they still run (checked in the Claude Code docs, "Configure permissions", on 2026-10-27):
- **file reads inside the project folder** (`.env`, `data/`, `tests/expected_results.md`…), even without a `Read` allow rule;
- **read-only shell commands** (`cat`, `ls`, `grep`, `find`…), in every mode. Before the fix, the search agent could run `cat .env`.

**Deny** (always wins over allow, "deny → ask → allow"):
- In the launchers (`--disallowedTools`), for the agents only:
  - `scripts/search.sh`: `Bash`, `WebFetch`, `WebSearch`, `Grep`, `Read(./.env)`, `Read(./.env.*)`, `Read(./tests/expected_results.md)`, `Read(./data/**)`, `Read(./.git/**)`, `Read(./.claude/settings.local.json)`, `Read(./.venv/**)`, `Read(./profile/**)` and `Read(./applications/**)` (your CV must never reach an agent that reads untrusted offers and sends free-text keywords to Indeed), and every claude.ai connector except Indeed `search_jobs` / `get_job_details`.
  - `scripts/track.sh`: `Bash`, `WebFetch`, `WebSearch`, `Read`, `Glob`, `Grep`, `Edit` (the tracking needs no file).
- In `.claude/settings.json` (shared with the project, for **every** session, mine included): `Read` and `Edit` of `.env` and `.env.*`, `Edit(./data/**)`.

Why two places: `tests/expected_results.md` and `data/` must stay readable when I develop (compare the results, debug), but never for the agents. `.env` must never be read by anyone.

**Tested on 2026-10-27** (decoy `.env` in a scratch folder, never the real one): `Read .env`, `Read .env.local`, `Edit .env` and even `cat .env` are refused; `Read tests/expected_results.md`, `ls` and reading `/etc/hosts` are refused for the search agent; `Glob data/**` finds nothing; the skill files can still be read; `./scripts/search.sh test` gives the same 8 scores.

**Limits**: a `Read` deny is "best effort" for tools other than Read (Grep, Glob, `cat`…). It is not a full security boundary: this is why the agents have no `Bash` at all. Rules like `Glob(path)` or `Write(path)` never match: use `Read(path)` and `Edit(path)`.

### 3.5 Launchers
**You launch the program yourself** (no automation for now):
```
./scripts/search.sh                   # normal mode
./scripts/search.sh test              # test mode
MODEL=opus ./scripts/search.sh test   # another model (default: sonnet)
```
- **Default model: Sonnet**.
- Gives **the date and time** to the agent in the prompt (it cannot read them alone, without a shell).
- Runs `claude -p` with `--permission-mode dontAsk`: only the tools listed in the script are allowed, everything else is refused without asking.
- `--mcp-config .mcp.json`, without `--strict-mcp-config`: the Indeed connector must be visible. Safety: `dontAsk` refuses every tool that is not allowed, and the other connectors are in `DENIED_TOOLS`.

**Containers**: `scripts/agent_docker.sh` runs each agent and its MCP servers in Docker, as a second wall behind the tool rules: a file that is not mounted cannot be read, even if a rule is wrong. Mounted by job: `CLAUDE.md`, `.mcp.json`, `mcp/`, `.claude/settings.json`, `data/` (all) + its own skill; search: `reports/` and `config/search.json` (in test mode: `tests/fake_offers.json` instead of the settings); apply: `profile/cv.md`, `profile/email-base.md`, `config/search.json` and only its `OUT_DIR`. Only `LBA_API_KEY` (search and apply) and, if there is no login in the volume, `CLAUDE_CODE_OAUTH_TOKEN` are taken from `.env`. `--read-only`, `--cap-drop ALL`, `no-new-privileges`, non-root user, process and memory limits. The login stays in the volume `agent-stage-claude`. Limits: the network is open (the servers need it), and an agent shares its container with its MCP servers. Scripts that use no LLM (`progress.py`, `check_links.py`, `offer_keywords.py`, `applications_index.py`) stay on the host.

**Application drafts**: `./scripts/apply.sh <id | company | offer text>` opens a chat (Sonnet) with the `prepare-application` skill. `--tools "Skill,Read,Write,Edit"`: the model sees no other built-in tool (safer, and a prompt about 4 000 tokens smaller, which matters a lot for a local model). Allowed: `Read(./profile/**)`, `Edit(./$OUT_DIR/**)` (also Write; `OUT_DIR` is `applications` by default), `memory.find`, the 2 `get_offer_details`. Only when the whole request is an `indeed:` id or an Indeed link, or when `apply_all.sh` gives an Indeed link in `OFFER_LINK` (never because the word is somewhere in a text): the 2 Indeed connector tools (`search_jobs`, `get_job_details`; an Indeed job id changes at each call, so the skill searches again by title and company), without `--strict-mcp-config`, and the other claude.ai connectors are explicitly refused, as in `search.sh`. Otherwise `--strict-mcp-config`: no claude.ai connector at all (the free-text `search_jobs` keyword is a way to leak your CV if an offer contains a prompt injection). Refused: `Bash`, web, `Edit(./profile/**)`, all tracking and search-memory writes. `profile/email-base.md` is the base of the emails: the agent keeps its fixed text and fills in its `{...}` parts. It writes one file with 5 headings: Offre, Destinataire, Manque, À vérifier et points importants, Mail. Nothing is sent: you read and send.
After the agent, the script itself (not the agent) checks every new file of `OUT_DIR` (sub-folders too): only `.md` files, no image, no HTML tag (even with the attributes on the next line), no attribute that loads something (`src=`, `href=`…), no `//host` URL, no URL that is not already in `profile/cv.md` or `profile/email-base.md`. Else it prints ⚠ DANGER and exits with code 3 (an image opened in a Markdown preview can send data in its URL).
`./scripts/apply_all.sh [report.md] [numbers...]` runs `apply.sh` with `BATCH=1` (`claude -p`, no chat) for each offer of a report, with `< /dev/null` (else `claude -p` reads the loop's stdin, i.e. the other offers). It first runs `check_links.py`: a report with a DANGER gives no email (exit code 4). The title, company and link of the report come from offer texts: they go in `parts/NN-company/offer-data.md`, read by the agent as data, and never enter its prompt. Each offer gets its own agent and its own `OUT_DIR` (`applications/<report name>/parts/NN-company/`), so the agent can write only there and the DANGER check of `apply.sh` reads only that offer. `scripts/applications_index.py` (run by the script, not the agent) parses the "## Top" section of the report (every field is untrusted: control characters removed, folder names `a-z0-9-` only), gives the state of each offer (`done` = a valid draft exists → skipped; `applied` = an `application` row in the tracking, matched by offer id or by company → skipped), and joins the drafts and their `keywords.md` in `mails.md` (the fields of the report: no HTML, only `https://` links). When no offer is failed, not done or DANGER, `applications_index.py clean` deletes `parts/`; `mails.md` is then never rewritten. It opens the memory database **read-only** (`mode=ro`, `MEMORY_DB` respected).
Before each offer, `apply_all.sh` runs `scripts/offer_keywords.py <link> <folder>` (code, no LLM): it finds the offer id from the link (memory database, read-only), calls `get_offer_details` of the source server **directly in Python** (same code and checks as for the agent; Indeed is not supported), and looks for each keyword of `config/ats_keywords.txt` (whole words, no accents or case; spellings of 1-2 characters keep their case, and `C` does not match `C++`, `C#`, `C'est` or `R&D`) in the offer, then in `profile/cv.md`. It writes `keywords.md` and prints 2 lines added to the prompt of `apply.sh`. Only names from the keyword list are written or printed, never a word of the offer, so no prompt injection can go through it. Any error → the offer is run without keywords.
`mails.md` is written by the script, never by an agent. A draft counts only if it has exactly the 5 headings of the skill, in order, and nothing else that looks like a heading (else the offer stays in « not done or failed » and is run again). A DANGER draft is never copied: one image or link in it would make the whole file unsafe to preview. The link of each offer comes from the report (only `https://`), not from the agent.

**Your tracking**: `./scripts/track.sh` opens a chat (Sonnet by default) with the `tracking` skill. You talk simply, in French ("j'ai postulé chez Nova hier"), the agent shows a summary and **waits for your "oui"** before writing.
```
./scripts/track.sh                                         # shows the last rows
./scripts/track.sh "j'ai postulé chez Nova hier"   # starts with this message
```

## 4. Common format of an offer

All sources return the offers **in this format**. It is the "contract" between the MCP servers and the agent.

| Field | Type | Example |
|---|---|---|
| `id` | unique text | `"ats:lever:acme:123"` (source + original id → no collision between sources) |
| `source` | text | `"la_bonne_alternance"`, `"indeed"` |
| `title` | text | `"Stage Assistant comptable"` (original title of the offer) |
| `company` | text | `"Nova"` |
| `city` | text | `"Lyon 3e"` |
| `postal_code` | text | `"69003"` |
| `contract_type` | text | `"internship"`, `"work-study"`, `"CDD"`, `"CDI"`, `"temporary"`, `"freelance"`, `"not specified"` |
| `duration` | text | `"6 mois"` (as written in the offer) |
| `start_date` | text | `"mars 2028"` (as written in the offer) |
| `score_bonus` | number | Points out of 10 to add at the end of the scoring: 1.5 if the text mentions a « convention de stage », plus 2 if the title or text says « stage ou alternance » (computed by `mcp/score_bonus.py`, not by the LLM). Indeed has no such field |
| `remote_work` | text | `"on site"`, `"hybrid"`, `"full remote"`, `"not specified"` |
| `published_date` | ISO date | `"2026-10-24"` |
| `url` | text | link to the offer |
| `description` | text | full text of the offer |

Example of this format: `tests/fake_offers.json`.

## 5. Flow of a run

```
1. Launch (./scripts/search.sh → claude -p)
2. The agent loads CLAUDE.md + the search-offers skill
3. <each active source>.search_offers(...)  → short list
4. memory.filter_already_seen(ids)           → only the new ones
4a. memory.find_reposts(offers)             → the new ones already seen under another id: not analysed again
4b. <same source>.get_offer_details(ids)    → full offers (§4 format), 10 per call
5. LLM: eliminating criteria (reading the text)
6. LLM: score /10 + justification for each remaining offer
7. LLM: top 12, score ≥ 4/10 (with the minimums by place of `criteria.md`)
8. LLM: writes reports/YYYY-MM-DD.md (report-template.md), in French
9. memory.save_evaluations(...)              → ALL the evaluated offers
   (even those < 4/10, so they are not seen again next time)
```

An **eliminated** offer is saved too, with `score = null` and the reason: it will not come back.

## 6. File tree

```
agent-stage-public/
├── README.md             ← setup, commands, sources
├── .claude/
│   ├── settings.json         ← deny rules for every session (.env, data/), shared with the project
│   ├── settings.local.json   ← approved MCP servers (interactive sessions, ignored by git)
│   └── skills/
│       ├── search-offers/
│       │   ├── SKILL.md
│       │   ├── criteria.md        (private; criteria.example.md is the public model)
│       │   ├── searches.md        (private; searches.example.md is the public model)
│       │   └── report-template.md
│       └── tracking/SKILL.md
├── .mcp.json             ← declaration of your MCP servers
├── requirements.txt      ← Python dependencies (mcp, httpx, beautifulsoup4)
├── requirements.lock     ← the same, pinned by hash (generated)
├── LICENSE               ← MIT
├── .venv/                ← Python 3.13 environment (uv)
├── mcp/
│   ├── memory/server.py
│   ├── la_bonne_alternance/server.py
│   ├── ats/server.py      ← career pages (ATS: SmartRecruiters, Greenhouse, Lever, Ashby) of a few companies
│   ├── score_bonus.py    ← score_bonus field and senior title filter, shared by the offer servers
│   ├── returned_urls.py  ← logs every offer URL the servers return (data/returned_urls.jsonl)
│   └── search_config.py  ← reads config/search.json
├── scripts/
│   ├── search.sh         ← search
│   ├── track.sh          ← your tracking
│   ├── agent_docker.sh   ← runs an agent in a container: only the files of its job are mounted
│   ├── apply.sh          ← application draft (one file, same headings for all offers), skill `prepare-application`
│   ├── apply_all.sh      ← apply.sh for every offer of a report, can be run again to finish
│   ├── applications_index.py ← offers of a report for apply_all.sh, and applications/<report>/mails.md (all the emails)
│   ├── pipeline.sh       ← the whole day: unit tests → search → emails of all the offers (trial memory by default)
│   ├── offer_keywords.py ← keywords of an offer found in / missing from your CV (code), for apply_all.sh
│   ├── benchmark_llm.py  ← same draft by several models, short context (CV + 1 offer), output in applications/test-llm/
│   ├── progress.py       ← live progress of search.sh and apply_all.sh (reads the stream-json events)
│   └── check_links.py    ← checks the links of a report before I click (tricks + every link must be in data/returned_urls.jsonl)
├── config/
│   ├── search.json           (yours, ignored by git; search.example.json is the model)
│   └── ats_keywords.txt      (yours, ignored by git; ats_keywords.example.txt is the model)
├── docs/
│   ├── ARCHITECTURE.md   ← the how (this file)
│   └── COMMANDS.md       ← every command in one list
├── CLAUDE.md             ← agent rules + development rules (must stay at the root: Claude Code reads it there)
├── data/
│   ├── offers.db         ← SQLite (created by the memory server)
│   ├── returned_urls.jsonl ← URLs returned by the offer servers, read by check_links.py (the agent cannot read or edit data/)
│   └── backups/          ← one copy each time the server starts, if the database changed
├── reports/              ← one .md per run (in French)
├── tests/
│   ├── unit/             ← unit tests
│   ├── fake_offers.json
│   ├── fake_offer_apply.md
│   └── expected_results.md   (yours, ignored by git) ← ⚠️ never give this file to the agent
├── .env                  ← secret: LBA_API_KEY (never in Git)
└── .gitignore
```
