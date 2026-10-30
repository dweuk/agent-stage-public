"""Keywords of an offer found in my CV or missing from it, computed by code (not guessed by the LLM).

Run by scripts/apply_all.sh before the agent writes the drafts of an offer:
- gets the full offer text by calling get_offer_details of the source server directly (Python, no LLM),
- looks for each keyword of config/ats_keywords.txt in the offer, then in profile/cv.md,
- writes <folder>/keywords.md (in French: it is for me),
- prints 2 lines for the prompt of apply.sh, so the email reuses the exact words of the offer.

Only the names of ats_keywords.txt are written or printed, never a word of the offer: an offer text is untrusted
(prompt injection), so nothing from it reaches the prompt or the file.
The offer id is found with the link, in the memory database opened read-only (MEMORY_DB lets the tests use another
file), or given directly. Indeed offers are not supported (the Indeed connector belongs to claude.ai).

Usage:
    .venv/bin/python scripts/offer_keywords.py <link or offer id> <output folder>
    .venv/bin/python scripts/offer_keywords.py --text offer.txt <output folder>   (tests: offer text from a file)
"""

import asyncio
import contextlib
import importlib.util
import io
import logging
import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the agent-stage-public/ folder
DB_PATH = Path(os.environ.get("MEMORY_DB", ROOT / "data" / "offers.db"))
CV_PATH = ROOT / "profile" / "cv.md"
# config/ats_keywords.txt is yours (ignored by git); the example is used until it exists.
KEYWORDS_PATH = next(path for path in (ROOT / "config" / "ats_keywords.txt", ROOT / "config" / "ats_keywords.example.txt")
                     if path.exists())
SERVERS = {  # source of the offer id → its MCP server (the same code as for the agent)
    "la_bonne_alternance": "mcp/la_bonne_alternance/server.py",
    "ats": "mcp/ats/server.py",
}
OFFER_ID = re.compile(r"[a-z_]+:\S+")
SKIPPED_FIELDS = {"id", "url", "company", "date", "city", "source"}  # not about the job itself
SHORT = 2  # spellings this long or shorter (C, R…) must have the same case
logging.getLogger("httpx").setLevel(logging.WARNING)  # no line per HTTP request


def normalize(text: str) -> str:
    """No accents, curly apostrophes as straight ones: "Données d’entrée" → "Donnees d'entree"."""
    text = text.replace("’", "'")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def load_keywords() -> list[tuple[str, re.Pattern]]:
    """(name, pattern) for each line of ats_keywords.txt."""
    keywords = []
    for line in KEYWORDS_PATH.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        spellings = [spelling.strip() for spelling in line.split("|") if spelling.strip()]
        parts = []
        for spelling in spellings:
            word = re.escape(normalize(spelling))
            if len(spelling) <= SHORT:
                # "C" must not match "C++", "C#", "C'est", "C-level" or "R&D".
                parts.append(rf"(?-i:(?<![\w+#&]){word}(?![\w+#&'-]))")
            else:
                parts.append(rf"(?<![\w+#]){word}(?![\w+#])")
        keywords.append((spellings[0], re.compile("|".join(parts), re.IGNORECASE)))
    return keywords


def offer_id_of(link_or_id: str) -> str:
    if OFFER_ID.fullmatch(link_or_id) and not link_or_id.startswith("http"):
        return link_or_id
    if not DB_PATH.is_file():
        raise LookupError("no memory database: give the offer id")
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        row = db.execute("SELECT id FROM offers WHERE url = ?", (link_or_id,)).fetchone()
    finally:
        db.close()
    if not row:
        raise LookupError("link not found in the memory")
    return row[0]


def strings_of(value) -> list[str]:
    """Every text of an offer field (lists and dicts too)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, item in value.items() if key not in SKIPPED_FIELDS for text in strings_of(item)]
    if isinstance(value, list):
        return [text for item in value for text in strings_of(item)]
    return []


def fetch_offer_text(offer_id: str) -> str:
    source = offer_id.split(":", 1)[0]
    if source not in SERVERS:
        raise LookupError(f"source {source!r} not supported")
    spec = importlib.util.spec_from_file_location(f"{source}_server", ROOT / SERVERS[source])
    server = importlib.util.module_from_spec(spec)
    # The servers may print while they load or work: stdout is for apply_all.sh only.
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(server)
        offers = asyncio.run(server.get_offer_details([offer_id]))
    if not offers or "error" in offers[0]:
        raise LookupError(offers[0].get("error", "no answer") if offers else "no answer")
    return "\n".join(strings_of(offers[0]))


def compare(offer_text: str, cv_text: str) -> tuple[list[str], list[str]]:
    """(found in my CV, missing from my CV), among the keywords of the offer."""
    offer_text, cv_text = normalize(offer_text), normalize(cv_text)
    found, missing = [], []
    for name, pattern in load_keywords():
        if pattern.search(offer_text):
            (found if pattern.search(cv_text) else missing).append(name)
    return found, missing


def write_report(folder: Path, offer_id: str, found: list[str], missing: list[str]) -> Path:
    total = len(found) + len(missing)
    score = f"{len(found)}/{total} ({round(100 * len(found) / total)} %)" if total else "0/0"
    lines = [
        "# Mots-clés de l'offre (calculés par le code)",
        "",
        f"Offre : `{offer_id}`. Liste : `config/ats_keywords.txt`. Correspondance : **{score}**.",
        "",
        "## Dans l'offre et dans ton CV : à reprendre tels quels (CV, email, formulaire)",
        "",
        ", ".join(found) or "Aucun.",
        "",
        "## Dans l'offre, absents de ton CV : ne les ajoute que si c'est vrai",
        "",
        ", ".join(missing) or "Aucun.",
        "",
        "Un mot absent peut être une vraie compétence oubliée dans `profile/cv.md` : ajoute-la au CV, avec une preuve "
        "(projet, expérience). Sinon, n'en parle pas comme d'un acquis.",
        "",
    ]
    path = folder / "keywords.md"
    path.write_text("\n".join(lines))
    return path


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "--text":
        offer_id, offer_text, folder = "texte de test", Path(args[1]).read_text(), Path(args[2])
    elif len(args) == 2:
        folder = Path(args[1])
        try:
            offer_id = offer_id_of(args[0])
            offer_text = fetch_offer_text(offer_id)
        except (LookupError, OSError, sqlite3.Error) as error:
            print(f"Keywords: skipped ({error}).", file=sys.stderr)
            return
        except Exception as error:  # a server error (network…) must not stop apply_all.sh
            print(f"Keywords: skipped (server error: {type(error).__name__}).", file=sys.stderr)
            return
    else:
        sys.exit("Usage: offer_keywords.py <link or offer id> <output folder>")
    folder.mkdir(parents=True, exist_ok=True)
    found, missing = compare(offer_text, CV_PATH.read_text())
    path = write_report(folder, offer_id, found, missing)
    print(f"Keywords: {len(found)} found, {len(missing)} missing → {path}", file=sys.stderr)
    print(f"Keywords of the offer found in my CV (computed by code): {', '.join(found) or 'none'}")
    print(f"Keywords of the offer missing from my CV (computed by code): {', '.join(missing) or 'none'}")


if __name__ == "__main__":
    main()
