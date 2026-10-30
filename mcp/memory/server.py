"""MCP server `memory`: the agent's memory and my own tracking.

Two uses:
- the search agent: know which offers were already seen, and save its scores;
- me (with Sonnet, through ./scripts/track.sh): record what I do on my side
  (applications, follow-ups, interviews, offers found elsewhere…).

"Never lose anything" rule:
- no tool deletes or modifies a row: we only add rows;
- a copy of the database is made each time the server starts (data/backups/).

Started by Claude Code (see .mcp.json): .venv/bin/python mcp/memory/server.py
"""

import datetime
import os
import re
import sqlite3
import sys
import unicodedata
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]  # the agent-stage-public/ folder
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the mcp/ folder: search_config.py
from search_config import section  # noqa: E402

# MEMORY_DB lets the tests use another database.
DB_PATH = Path(os.environ.get("MEMORY_DB", ROOT / "data" / "offers.db"))
BACKUP_DIR = DB_PATH.parent / "backups"
BACKUPS_KEPT = 30  # keep the 30 most recent copies
SOURCE_PATTERN = re.compile(r"[a-z0-9_]{1,30}")  # source of add_offer: no ":" or "/" inside the id

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id        TEXT PRIMARY KEY,  -- "source:original_id", e.g. "la_bonne_alternance:0123abc"
    title     TEXT,
    company   TEXT,
    url       TEXT,
    status    TEXT NOT NULL,     -- kept / below_threshold / eliminated / repost / added_by_me
    score     REAL,              -- out of 10, NULL if eliminated, repost or added by me
    reason    TEXT,
    seen_at   TEXT NOT NULL,     -- date and time of saving
    city      TEXT               -- added on 2026-10-28 (NULL for older rows): used by find_reposts
);
CREATE TABLE IF NOT EXISTS tracking (
    num       INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT NOT NULL,     -- date of the action (YYYY-MM-DD)
    type      TEXT NOT NULL,     -- application, follow_up, interview…
    company   TEXT,
    offer_id  TEXT,              -- link to offers.id (can be empty)
    text      TEXT NOT NULL,
    added_at  TEXT NOT NULL      -- date and time of saving
);
"""

TrackingType = Literal[
    "application",  # I applied
    "follow_up",    # I followed up
    "interview",    # interview planned or done
    "answer",       # positive or neutral answer from the company
    "rejection",    # rejection from the company
    "dropped",      # I am no longer interested
    "note",         # anything else (contact, idea, info about the company…)
]


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    """Open the database, do everything in one transaction (all or nothing), then close it."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row  # read rows like dictionaries
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(offers)")}
        if "city" not in columns:  # database created before 2026-10-28: add the column, keep every row
            conn.execute("ALTER TABLE offers ADD COLUMN city TEXT")
        with conn:  # commit at the end, or roll everything back on error
            yield conn


def backup() -> None:
    """Copy the database into data/backups/, then delete the oldest copies.

    Only if the database changed since the newest copy: apply.sh starts this server once per offer, so a
    long run of apply_all.sh would else replace all the old copies with the same content.
    """
    if not DB_PATH.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    newest = max(BACKUP_DIR.glob("offers-*.db"), key=lambda p: p.stat().st_mtime, default=None)
    if newest and newest.stat().st_mtime >= DB_PATH.stat().st_mtime:
        return  # no write since the last copy (a read-only start does not change the file)
    name = f"offers-{datetime.datetime.now():%Y-%m-%d_%H%M%S}.db"
    with closing(sqlite3.connect(DB_PATH)) as source, closing(sqlite3.connect(BACKUP_DIR / name)) as copy:
        source.backup(copy)  # safe copy, even if the database is open elsewhere
    copies = sorted(BACKUP_DIR.glob("offers-*.db"))
    for old in copies[:-BACKUPS_KEPT]:
        old.unlink()


mcp = MCPServer(
    "memory",
    instructions=(
        "Memory of the offers already seen, and tracking of my actions (applications, follow-ups…). "
        "Nothing is ever deleted: to fix a mistake, add a new tracking row."
    ),
)


# ---------- Tools for the search agent ----------

@mcp.tool()
def filter_already_seen(ids: list[str]) -> list[str]:
    """Return only the ids never seen before (neither scored by the agent nor added by me).

    The order of the list is kept and duplicates are removed.
    """
    with connect() as conn:
        seen = {row["id"] for row in conn.execute("SELECT id FROM offers")}
    new_ids = []
    for offer_id in ids:
        if offer_id not in seen and offer_id not in new_ids:
            new_ids.append(offer_id)
    return new_ids


class Evaluation(BaseModel):
    id: str = Field(description='Id in the format "source:original_id"')
    title: str
    company: str
    url: str
    city: str = Field(default="", description="City of the offer, as in the short list (used to find reposts)")
    status: Literal["kept", "below_threshold", "eliminated", "repost"]
    score: float | None = Field(default=None, ge=0, le=10, description="Score out of 10, null if eliminated or repost")
    reason: str = Field(description="Justification, code + reason of the elimination, or the offer it is a repost of")


@mcp.tool()
def save_evaluations(evaluations: list[Evaluation]) -> dict:
    """Save the offers evaluated during a search (all of them: kept, below threshold, eliminated, repost).

    An offer already saved is not overwritten: the first evaluation is kept.
    """
    for ev in evaluations:
        if ev.status in ("kept", "below_threshold") and ev.score is None:
            raise ToolError(f"{ev.id}: a kept or below-threshold offer needs a score. Nothing was saved.")
    added, already_saved = [], []
    with connect() as conn:
        for ev in evaluations:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO offers (id, title, company, url, status, score, reason, seen_at, city)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ev.id, ev.title, ev.company, ev.url, ev.status, ev.score, ev.reason, now(), ev.city or None),
            )
            (added if cursor.rowcount == 1 else already_saved).append(ev.id)
    return {"added": len(added), "already_saved": already_saved}


# ---------- Reposts: the same offer seen again with another id ----------
# The same offer can come back with a new id: on another source (the same company can post on several),
# or republished by the company. Same company + same title + same area = the same offer.
# An offer seen again and again for months may be a "ghost job" (an offer that nobody really recruits for).

GHOST_DAYS = 60  # an offer first seen more than 60 days ago is a possible ghost job
GENDER_MARKS = re.compile(r"\b(?:h\s*/\s*f|f\s*/\s*h|m\s*/\s*f|f\s*/\s*m)(?:\s*/\s*(?:x|nb|d))?\b")
LEGAL_WORDS = re.compile(r"\b(?:sas|sasu|sa|sarl|eurl|group|groupe|france|inc|ltd|gmbh)\b")
# From config/search.json. Departments that count as one area, and names of towns when a text has no department.
AREA_OF_DEPARTMENT = {department: area for area, departments in section("memory").get("department_groups", {}).items()
                      for department in departments}
CITY_AREAS = section("memory").get("city_areas", {})


def plain(text: str) -> str:
    """Lower case, no accents: 'Chargé(e) de Projet' → 'charge(e) de projet'."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def offer_key(title: str, company: str) -> str | None:
    """Same key = same offer. None if the company is unknown (then we cannot tell)."""
    company = re.sub(r"[^a-z0-9]", "", LEGAL_WORDS.sub(" ", plain(company)))
    title = " ".join(re.findall(r"[a-z0-9]+", GENDER_MARKS.sub(" ", plain(title))))
    if not company or company == "notspecified" or not title:
        return None
    return f"{company}|{title}"


def area_of(city: str) -> str:
    """Area of a city text of any source: an area of the configuration, a department number ('69'), or '' if unknown.

    Examples: '69 - Lyon 3e', 'Villeurbanne (69)', 'Lyon, Auvergne-Rhône-Alpes, France', 'Lyon'.
    """
    text = plain(city)
    found = re.search(r"\b(\d{2})\d{3}\b", text) or re.search(r"\((\d{2})\)", text) or re.match(r"\s*(\d{2})\s*-", text)
    if found:
        return AREA_OF_DEPARTMENT.get(found.group(1), found.group(1))
    for name, area in CITY_AREAS.items():
        if plain(name) in text:
            return area
    return ""


class ShortOffer(BaseModel):
    id: str
    title: str
    company: str
    city: str = ""


@mcp.tool()
def find_reposts(offers: list[ShortOffer]) -> dict:
    """Among NEW offers (returned by filter_already_seen), find the reposts: offers already in memory under
    another id (same company, same title, same area), e.g. the same offer on another source.

    Returns only the reposts. For each one: the id of the offer already seen (`same_as`, the last evaluated one),
    its status and score, the date it was first seen, how many times it was seen, and `possible_ghost`
    (first seen more than 60 days ago: maybe nobody really recruits for it).
    """
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT id, title, company, city, status, score, seen_at FROM offers")]
    by_key = {}
    for row in rows:
        key = offer_key(row["title"], row["company"])
        if key:
            by_key.setdefault(key, []).append(row)

    today = datetime.date.today()
    reposts = []
    for offer in offers:
        key = offer_key(offer.title, offer.company)
        area = area_of(offer.city)
        # An unknown area (old rows have no city) is not a difference: it matches any area.
        same = [r for r in by_key.get(key, []) if r["id"] != offer.id
                and (not area or not area_of(r["city"] or "") or area_of(r["city"] or "") == area)]
        if not same:
            continue
        evaluated = [r for r in same if r["status"] != "repost"] or same
        last = max(evaluated, key=lambda r: r["seen_at"])
        first_seen = min(r["seen_at"] for r in same)[:10]
        reposts.append({
            "id": offer.id,
            "same_as": last["id"],
            "same_as_status": last["status"],
            "same_as_score": last["score"],
            "first_seen": first_seen,
            "times_seen": len(same),
            "possible_ghost": (today - datetime.date.fromisoformat(first_seen)).days > GHOST_DAYS,
        })
    return {"checked": len(offers), "reposts": reposts}


# ---------- Tools for my tracking (with Sonnet) ----------

def check_date(text: str) -> str:
    if not text:
        return datetime.date.today().isoformat()
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        raise ToolError(f"Invalid date: '{text}'. Expected format: YYYY-MM-DD.")


@mcp.tool()
def add_offer(title: str, company: str, url: str = "", source: str = "manual", text: str = "") -> dict:
    """Add an offer that I found myself (LinkedIn, company website, job fair…).

    The agent will not suggest it again. Returns the new id, to use next in add_tracking.
    source: one simple word, e.g. "linkedin", "hellowork", "manual".
    text: what I want to remember about the offer (optional).
    """
    source = source.strip().lower().replace(" ", "_") or "manual"
    if not SOURCE_PATTERN.fullmatch(source):
        raise ToolError(f"Invalid source {source!r}: one simple word (letters, digits, _), 30 characters at most.")
    with connect() as conn:
        n = 1
        while conn.execute("SELECT 1 FROM offers WHERE id = ?", (f"{source}:{n}",)).fetchone():
            n += 1
        offer_id = f"{source}:{n}"
        conn.execute(
            "INSERT INTO offers (id, title, company, url, status, score, reason, seen_at)"
            " VALUES (?, ?, ?, ?, 'added_by_me', NULL, ?, ?)",
            (offer_id, title, company, url, text, now()),
        )
    return {"id": offer_id, "title": title, "company": company}


@mcp.tool()
def add_tracking(type: TrackingType, text: str, company: str = "", offer_id: str = "", date: str = "") -> dict:
    """Add a row to my tracking (something I did on my side).

    date: date of the action, format YYYY-MM-DD. Empty = today.
    offer_id: id of an offer already in memory (find it with `find`). Optional.
    A row is never modified: to fix a mistake, add a new row of type "note".
    """
    day = check_date(date)
    with connect() as conn:
        if offer_id:
            offer = conn.execute("SELECT company FROM offers WHERE id = ?", (offer_id,)).fetchone()
            if offer is None:
                raise ToolError(f"No offer with id '{offer_id}'. Use `find`, or `add_offer` first.")
            company = company or offer["company"]
        cursor = conn.execute(
            "INSERT INTO tracking (date, type, company, offer_id, text, added_at) VALUES (?, ?, ?, ?, ?, ?)",
            (day, type, company, offer_id or None, text, now()),
        )
    return {"num": cursor.lastrowid, "date": day, "type": type, "company": company, "offer_id": offer_id}


@mcp.tool()
def find(text: str) -> dict:
    """Look for a word (company, title, id, or a word of a note) in the offers and in the tracking.

    For each offer found, also return its tracking rows.
    """
    pattern = f"%{text}%"
    with connect() as conn:
        offers = [dict(o) for o in conn.execute(
            "SELECT * FROM offers WHERE id LIKE ? OR title LIKE ? OR company LIKE ? ORDER BY seen_at DESC LIMIT 20",
            (pattern, pattern, pattern),
        )]
        for offer in offers:
            offer["tracking"] = [dict(t) for t in conn.execute(
                "SELECT * FROM tracking WHERE offer_id = ? ORDER BY date, num", (offer["id"],)
            )]
        tracking = [dict(t) for t in conn.execute(
            "SELECT * FROM tracking WHERE (company LIKE ? OR text LIKE ?) ORDER BY date DESC, num DESC LIMIT 20",
            (pattern, pattern),
        )]
    return {"offers": offers, "tracking": tracking}


@mcp.tool()
def history(limit: int = 20) -> list[dict]:
    """Return the last rows of my tracking, from the most recent to the oldest."""
    with connect() as conn:
        return [dict(t) for t in conn.execute(
            "SELECT * FROM tracking ORDER BY date DESC, num DESC LIMIT ?", (max(1, min(limit, 200)),)
        )]


if __name__ == "__main__":
    backup()
    mcp.run()  # stdio transport: Claude Code talks to the server through standard input and output
