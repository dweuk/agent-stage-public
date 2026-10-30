"""MCP server `la-bonne-alternance`: work-study offers from the La bonne alternance API (public service).

The API gathers work-study offers from La bonne alternance itself, from partners (HelloWork, Meteojob…)
and from France Travail. It has NO keyword search: it searches by ROME codes (French directory of jobs).
The ROME codes and the places are in config/search.json.

How it works:
1. `search_offers` runs one search per place (GPS circle), with all the ROME codes.
   If a search reaches the API limit (150 offers per source), it is redone with one ROME code at a time.
   Offers whose postal code is outside the `departments` of the place are removed (E3_LOCATION).
   It returns a SHORT list (no description). The full offers stay in memory inside this server.
2. The agent removes the offers already seen with the `memory` server.
3. `get_offer_details` returns the full offers, in the common format (§4 of docs/ARCHITECTURE.md).

Secret: LBA_API_KEY, read from the .env file (never in the code). It must be a PRODUCTION key:
a sandbox key returns test data, not real offers.
API documentation: https://api.apprentissage.beta.gouv.fr/en/documentation-technique (operation jobSearch).
Manual test: .venv/bin/python mcp/la_bonne_alternance/server.py --test
"""

import asyncio
import html
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the mcp/ folder: score_bonus.py, returned_urls.py
from returned_urls import logs_url  # noqa: E402
from score_bonus import is_senior_title, offer_bonus  # noqa: E402
from search_config import missing_config, section  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]  # the agent-stage-public/ folder

API_URL = "https://api.apprentissage.beta.gouv.fr/api"
SEARCH_PATH = "/job/v1/search"
OFFER_PATH = "/job/v1/offer/{id}"
# A La bonne alternance id = 24 hexadecimal characters. The ids come from the LLM and go into the URL:
# anything else ("../", "?", "/") could call another route of the API with my key.
LBA_ID_PATTERN = re.compile(r"la_bonne_alternance:([0-9a-f]{24})")
SANDBOX_MARK = "labonnealternance-recette"  # in the URLs of the test environment

# ROME 4.0 codes of the wanted jobs and search zone, from config/search.json.
# We search with GPS coordinates: on 2026-10-27, the `departements` filter of the API returned half as many offers
# (it misses offers without a postal code in the address). A circle can cover other departments: the code removes
# the offers whose postal code is outside `departments` (E3_LOCATION). An offer without a postal code is kept.
SETTINGS = section("la_bonne_alternance")
ROMES = SETTINGS.get("romes", {})
PLACES = SETTINGS.get("places", {})

RESULT_LIMIT = 150      # the API returns at most 150 offers per source and per call
CALLS_PER_MINUTE = 50   # the API allows 60: keep a margin
PARALLEL_CALLS = 3
MAX_DETAILS = 10         # ids per get_offer_details call: 20 full offers were too big for one tool answer
MAX_ATTEMPTS = 4        # tries per call when the API says "too many requests" (429) or fails (5xx)
RETRY_WAIT = 15         # seconds between two tries (the Retry-After header is not used: it could be huge)

REMOTE_WORK = {"onsite": "on site", "hybrid": "hybrid", "remote": "full remote"}


def load_env() -> None:
    """Read the .env file (NAME=value lines) into os.environ. Never prints it."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


class LaBonneAlternanceClient:
    def __init__(self):
        self._http = httpx.AsyncClient(timeout=30)
        self._limit = asyncio.Semaphore(PARALLEL_CALLS)
        self._lock = asyncio.Lock()
        self._next_call = 0.0

    async def _wait_turn(self) -> None:
        """Space the calls out: at most CALLS_PER_MINUTE calls per minute."""
        async with self._lock:
            now = time.monotonic()
            wait = self._next_call - now
            self._next_call = max(now, self._next_call) + 60 / CALLS_PER_MINUTE
        if wait > 0:
            await asyncio.sleep(wait)

    async def get(self, path: str, params: dict | None = None) -> httpx.Response:
        """GET with the API key. If the API says "too many requests" (429) or fails (5xx):
        wait RETRY_WAIT seconds and try again, MAX_ATTEMPTS tries in total."""
        key = os.environ.get("LBA_API_KEY", "")
        if not key:
            raise ToolError("LBA_API_KEY is missing from the .env file.")
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        async with self._limit:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                await self._wait_turn()
                response = await self._http.get(API_URL + path, params=params, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < MAX_ATTEMPTS:
                        await asyncio.sleep(RETRY_WAIT)
                    continue
                if response.status_code in (401, 403):
                    # Do not return the response body: never risk showing a secret.
                    raise ToolError(f"La bonne alternance refused the API key (HTTP {response.status_code}). "
                                    "Check LBA_API_KEY in the .env file.")
                return response
            return response


client = None   # created on the first call (it needs the server's asyncio loop)
CACHE = {}      # common id → raw offer, filled by search_offers


def common_id(job: dict) -> str:
    identifier = job.get("identifier") or {}
    lba_id = identifier.get("id") or f"{identifier.get('partner_label')}-{identifier.get('partner_job_id')}"
    return f"la_bonne_alternance:{lba_id}"


def postal_code(job: dict) -> str | None:
    """'12 rue X 69003 Lyon' → '69003'. None if the address has no postal code."""
    address = ((job.get("workplace") or {}).get("location") or {}).get("address") or ""
    found = re.search(r"\b\d{5}\b", address)
    return found.group(0) if found else None


def text(value: str | None) -> str:
    """Some texts come with HTML entities ('&amp;'): turn them back into normal characters."""
    return html.unescape(value or "").strip()


def start_date(contract: dict) -> str:
    if contract.get("start_type") == "des_que_possible":
        return "as soon as possible"
    if contract.get("start"):
        flexible = " (flexible)" if contract.get("start_is_flexible") else ""
        return contract["start"][:10] + flexible
    return "not specified"


def join(values: list | None) -> str:
    return "; ".join(str(v) for v in values or []) or "not specified"


@logs_url  # writes the URL in data/returned_urls.jsonl, for scripts/check_links.py
def common_format(job: dict) -> dict:
    """Raw La bonne alternance offer → common format (§4 of docs/ARCHITECTURE.md)."""
    identifier = job.get("identifier") or {}
    workplace = job.get("workplace") or {}
    contract = job.get("contract") or {}
    offer = job.get("offer") or {}
    address = (workplace.get("location") or {}).get("address") or ""
    diploma = offer.get("target_diploma") or {}

    # Useful information for the scoring grid that has no field in the common format.
    extra = [
        f"Contract (La bonne alternance): {join(contract.get('type'))}",
        f"Target diploma: {diploma.get('label') or 'not specified'}",
        f"Skills wanted: {join(offer.get('desired_skills'))}",
        f"Skills to learn: {join(offer.get('to_be_acquired_skills'))}",
        f"Access conditions: {join(offer.get('access_conditions'))}",
        f"Company size: {workplace.get('size') or 'not specified'}",
        f"Original source: {identifier.get('partner_label') or 'not specified'}",
    ]
    if job.get("is_delegated"):
        extra.append("Posted by a training centre on behalf of the company (is_delegated).")
    description = text(offer.get("description"))
    if workplace.get("description"):
        description += "\n\nAbout the company: " + text(workplace["description"])
    description += "\n\n" + "\n".join(extra)

    title = text(offer.get("title")) or "not specified"
    return {
        "id": common_id(job),
        "source": "la_bonne_alternance",
        "title": title,
        "company": text(workplace.get("brand") or workplace.get("name") or workplace.get("legal_name")) or "not specified",
        "city": address or "not specified",
        "postal_code": postal_code(job) or "not specified",
        "contract_type": "work-study",   # this API only has work-study offers
        "duration": f"{contract['duration']} mois" if contract.get("duration") else "not specified",
        "start_date": start_date(contract),
        "remote_work": REMOTE_WORK.get(contract.get("remote"), "not specified"),
        "published_date": ((offer.get("publication") or {}).get("creation") or "")[:10] or "not specified",
        "url": (job.get("apply") or {}).get("url") or "not specified",
        "description": description,
        "score_bonus": offer_bonus(title, description),  # points for the agent to add at the end (mcp/score_bonus.py)
    }


def parse_date(value) -> datetime | None:
    """ISO date of the API → datetime with a time zone (UTC if none). None if missing or malformed:
    one strange offer must not break the whole search."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # else comparing with an aware datetime raises TypeError
    return parsed


def is_open(job: dict, oldest: datetime) -> bool:
    """Active, not expired, and published after `oldest`. An unreadable date counts as missing."""
    offer = job.get("offer") or {}
    publication = offer.get("publication") or {}
    if offer.get("status", "Active") != "Active":
        return False
    expiration = parse_date(publication.get("expiration"))
    if expiration and expiration < datetime.now(timezone.utc):
        return False
    creation = parse_date(publication.get("creation"))
    return not creation or creation >= oldest


async def one_search(place: str, romes: list[str]) -> tuple[list[dict], list[str]]:
    """One call: one place, some ROME codes. Returns (offers, problems)."""
    codes = romes[0] if len(romes) == 1 else "all ROME codes"
    try:
        response = await client.get(SEARCH_PATH, {"romes": ",".join(romes), **PLACES[place]["params"]})
    except httpx.HTTPError as error:  # timeout, no network…: lose this search only, not the whole gather
        return [], [f"{place} / {codes}: {type(error).__name__}"]
    if response.status_code != 200:
        return [], [f"{place} / {codes}: HTTP {response.status_code}"]
    try:
        data = response.json()
    except ValueError:  # an HTML page (maintenance…) instead of JSON
        return [], [f"{place} / {codes}: the API did not answer JSON"]
    problems = [f"{place}: {w.get('message')}" for w in data.get("warnings") or []]
    return data.get("jobs") or [], problems


async def search_place(place: str) -> tuple[list[dict], list[str], int]:
    """All the offers of one place. Returns (offers, problems, number of calls)."""
    jobs, problems = await one_search(place, list(ROMES))
    if len(jobs) < RESULT_LIMIT:
        return jobs, problems, 1
    # The limit may have cut the list: redo the search with one ROME code at a time.
    results = await asyncio.gather(*(one_search(place, [rome]) for rome in ROMES))
    jobs, problems = [], []
    for rome, (rome_jobs, rome_problems) in zip(ROMES, results):
        jobs += rome_jobs
        problems += rome_problems
        if len(rome_jobs) >= RESULT_LIMIT:
            problems.append(f"{place} / {rome}: {RESULT_LIMIT} offers or more, the list may be incomplete")
    return jobs, problems, 1 + len(ROMES)


mcp = MCPServer(
    "la-bonne-alternance",
    instructions="Work-study offers from the La bonne alternance API. Call search_offers, then get_offer_details for the new offers.",
)


@mcp.tool()
async def search_offers(published_since_days: int = 31) -> dict:
    """Search work-study (alternance) offers in the zone and for the jobs of the configuration.
    The jobs (ROME codes) and the places are set there: there are no keywords.

    Returns a SHORT list (id, title, company, city, contract_type, published_date), without duplicates.
    Offers whose postal code is outside the zone are already removed: they are in `removed_by_code` (E3_LOCATION).
    Offers whose title asks for a senior profile (senior, confirmé, expérimenté) are left out: only their number is in `skipped_senior_title`.
    Closed or expired offers, and offers older than published_since_days, are skipped (`old_or_closed_skipped`).
    To read a full offer, call get_offer_details next.
    published_since_days: from 1 to 365.
    """
    global client
    if not (PLACES and ROMES):
        raise ToolError(missing_config("la_bonne_alternance"))
    if not 1 <= published_since_days <= 365:
        raise ToolError("published_since_days must be between 1 and 365.")
    client = client or LaBonneAlternanceClient()
    oldest = datetime.now(timezone.utc) - timedelta(days=published_since_days)

    results = await asyncio.gather(*(search_place(place) for place in PLACES))

    offers, removed, errors, raw_count, calls, old_or_closed, handled = {}, [], [], 0, 0, 0, set()
    skipped_senior = 0
    for place, (jobs, problems, call_count) in zip(PLACES, results):
        allowed_departments = tuple(PLACES[place].get("departments") or ())
        errors += problems
        calls += call_count
        for job in jobs:
            raw_count += 1
            offer_id = common_id(job)
            if offer_id in handled:  # same offer found by another place or another ROME code
                continue
            handled.add(offer_id)
            CACHE[offer_id] = job
            if not is_open(job, oldest):
                old_or_closed += 1
                continue
            code = postal_code(job)
            if allowed_departments and code and not code.startswith(allowed_departments):
                short = common_format(job)
                removed.append({"id": offer_id, "title": short["title"], "company": short["company"], "url": short["url"],
                                "reason": f"E3_LOCATION: postal code {code} is outside the zone (address field)"})
                continue
            if is_senior_title(common_format(job)["title"]):
                skipped_senior += 1  # not saved by the agent: it may come back, and be filtered again
                continue
            offers[offer_id] = job

    if any(SANDBOX_MARK in common_format(job)["url"] for job in offers.values()):
        raise ToolError("These offers come from the La bonne alternance TEST environment: LBA_API_KEY is a "
                        "sandbox key. Create a production key.")

    short_fields = ("id", "title", "company", "city", "contract_type", "published_date")
    return {
        "searches": calls,
        "results_with_duplicates": raw_count,
        "offer_count": len(offers),
        "offers": [{k: v for k, v in common_format(o).items() if k in short_fields} for o in offers.values()],
        "removed_by_code": removed,
        "skipped_senior_title": skipped_senior,
        "old_or_closed_skipped": old_or_closed,
        "errors": errors,
    }


@mcp.tool()
async def get_offer_details(ids: list[str]) -> list[dict]:
    """Return the full offers (common format, with the description) for these ids.

    Use the ids returned by search_offers of this server. At most 10 ids per call: call several times if needed.
    """
    global client
    if len(ids) > MAX_DETAILS:
        raise ToolError(f"At most {MAX_DETAILS} ids per call. Split the list and call several times.")
    client = client or LaBonneAlternanceClient()
    offers = []
    for offer_id in ids:
        if offer_id not in CACHE:
            # Not seen in the last search. Only a valid La bonne alternance id can be asked to the API.
            valid = LBA_ID_PATTERN.fullmatch(offer_id)
            if not valid:
                offers.append({"id": offer_id, "error": "invalid id: use an id returned by search_offers of this server"})
                continue
            try:
                response = await client.get(OFFER_PATH.format(id=valid.group(1)))
            except httpx.HTTPError as error:
                offers.append({"id": offer_id, "error": type(error).__name__})
                continue
            if response.status_code != 200:
                offers.append({"id": offer_id, "error": f"HTTP {response.status_code}: offer not found or expired"})
                continue
            try:
                CACHE[offer_id] = response.json()
            except ValueError:
                offers.append({"id": offer_id, "error": "the API did not answer JSON"})
                continue
        offers.append(common_format(CACHE[offer_id]))
    return offers


async def manual_test() -> None:
    """Small test without Claude: one full search, then the details of one offer. Prints no secret."""
    global client
    client = LaBonneAlternanceClient()
    result = await search_offers(31)
    print(f"✅ {result['searches']} calls, {result['results_with_duplicates']} results, "
          f"{result['offer_count']} offers (last 31 days), {result['old_or_closed_skipped']} old or closed, "
          f"errors: {result['errors'] or 'none'}")
    for offer in result["offers"][:8]:
        print(f"   - {offer['published_date']} | {offer['title']} | {offer['company']} | {offer['city']}")
    if result["offers"]:
        detail = (await get_offer_details([result["offers"][0]["id"]]))[0]
        print(f"✅ Details of the 1st offer: start {detail['start_date']}, duration {detail['duration']}, "
              f"remote work {detail['remote_work']}, {len(detail['description'])} characters, url: {detail['url']}")


load_env()

if __name__ == "__main__":
    if "--test" in sys.argv:
        asyncio.run(manual_test())
    else:
        mcp.run()
