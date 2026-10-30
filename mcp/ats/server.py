"""MCP server `ats`: internship and work-study offers from the career pages of a few companies.

Many companies publish their offers with an ATS (applicant tracking system: the software of their career page).
Some ATS give a free, public and official JSON API per company, made to be read by programs:
- SmartRecruiters: https://api.smartrecruiters.com/v1/companies/{board}/postings;
- Greenhouse: https://boards-api.greenhouse.io/v1/boards/{board}/jobs;
- Lever: https://api.lever.co/v0/postings/{board};
- Ashby: https://api.ashbyhq.com/posting-api/job-board/{board}.
Idea taken from https://github.com/strelov1/freehire (scripts/ats_boards.py, MIT licence).

The companies are in `boards` of config/search.json, chosen by the user. Nothing that comes from the LLM goes into a list URL, and an offer id is checked with ID_PATTERN.
To add a company: find its board on its career page (e.g. jobs.smartrecruiters.com/{board}/…), add one line there.

Filters of the code (the agent never sees these offers):
- only internships and work-study (title, or the "internship" level of SmartRecruiters);
- only titles close to the wanted jobs (JOB_TITLE, from `job_title_patterns`);
- only the zone: postal code in `zone_departments`, or a city name of `zone_cities`;
- published less than `published_since_days` days ago; no senior title (`is_senior_title`).

Calls: one at a time, PAUSE seconds between two calls, at most MAX_REQUESTS_PER_RUN requests per run.
No secret: the APIs need no account.
Manual test: .venv/bin/python mcp/ats/server.py --test
"""

import asyncio
import datetime
import html
import re
import sys
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the mcp/ folder: score_bonus.py, returned_urls.py
from returned_urls import logs_url  # noqa: E402
from score_bonus import is_senior_title, offer_bonus  # noqa: E402
from search_config import missing_config, section  # noqa: E402

# Company name shown in the report → (ATS, board). The board is the name of the company inside the ATS.
SETTINGS = section("ats")
BOARDS = {name: tuple(board) for name, board in SETTINGS.get("boards", {}).items()}
COMPANY_OF = {board: name for name, board in BOARDS.items()}

LIST_URL = {
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{board}/postings",
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{board}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{board}",
}
SR_DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{board}/postings/{id}"
DETAIL_URL = {  # one offer (Ashby has no such route)
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}",
    "lever": "https://api.lever.co/v0/postings/{board}/{id}",
}
# The link of an offer is built from its id, never copied from the API answer.
PUBLIC_URL = {
    "smartrecruiters": "https://jobs.smartrecruiters.com/{board}/{id}",
    "greenhouse": "https://job-boards.greenhouse.io/{board}/jobs/{id}",
    "lever": "https://jobs.lever.co/{board}/{id}",
    "ashby": "https://jobs.ashbyhq.com/{board}/{id}",
}
# The ids come from the LLM and go into a URL: anything else ("../", "?", "/") must be refused.
ID_PATTERN = re.compile(r"ats:(smartrecruiters|greenhouse|lever|ashby):([A-Za-z0-9_-]{1,40}):([A-Za-z0-9-]{1,64})")

JUNIOR_TITLE = re.compile(r"\b(stage|stagiaire|intern(ship)?|alternan\w*|apprenti\w*|work[- ]study)\b", re.IGNORECASE)
WORK_STUDY_TITLE = re.compile(r"\b(alternan\w*|apprenti\w*|work[- ]study)\b", re.IGNORECASE)
# These companies may have many offers far from the wanted jobs: keep only the titles of `job_title_patterns`.
# The others are only counted in `skipped_by_title`.
JOB_TITLE = re.compile("|".join(SETTINGS.get("job_title_patterns", [])), re.IGNORECASE)
ZONE_DEPARTMENTS = tuple(SETTINGS.get("zone_departments", []))
# Used only when the API gives no postal code (Greenhouse, Lever, Ashby). No city: nothing matches.
ZONE_CITY_PATTERN = re.compile(rf"\b({'|'.join(SETTINGS.get('zone_cities', []))})\b" if SETTINGS.get("zone_cities") else r"(?!)",
                               re.IGNORECASE)

SR_PAGE_SIZE = 100
SR_MAX_PAGES = 12        # 1,200 offers in France per company at most
PAUSE = 1.0              # seconds between two calls (official APIs: no need for long random pauses)
MAX_DETAILS = 5          # ids per get_offer_details call: 10 full offers were too big for one tool answer
MAX_DETAILS_PER_RUN = 40 # detail requests per run (only SmartRecruiters needs them after search_offers)
MAX_REQUESTS_PER_RUN = 120
MAX_ATTEMPTS = 4         # tries per call when the API says "too many requests" (429) or fails (5xx)
RETRY_WAIT = 15          # seconds between two tries (the Retry-After header is not used)
HEADERS = {"Accept": "application/json"}


class AtsClient:
    def __init__(self):
        self._lock = asyncio.Lock()  # one call at a time
        self._last_call = 0.0
        self._http = httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=False)
        self.request_count = 0

    async def get_json(self, url: str, params: dict | None = None):
        """GET → JSON. 429 or 5xx: wait RETRY_WAIT seconds and try again, MAX_ATTEMPTS tries in total.
        Raises RuntimeError with a short message if it fails."""
        async with self._lock:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                if self.request_count >= MAX_REQUESTS_PER_RUN:
                    raise RuntimeError(f"budget of {MAX_REQUESTS_PER_RUN} requests per run reached")
                wait = self._last_call + PAUSE - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self.request_count += 1
                self._last_call = time.monotonic()
                response = await self._http.get(url, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < MAX_ATTEMPTS:
                        await asyncio.sleep(RETRY_WAIT)
                    continue
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                try:
                    return response.json()
                except ValueError:
                    raise RuntimeError("the answer is not JSON")
            raise RuntimeError(f"HTTP {response.status_code} {MAX_ATTEMPTS} times in a row")


client = None   # created on the first call (it needs the server's asyncio loop)
CACHE = {}      # common id → offer (raw fields, then with the description), filled by search_offers
details_count = 0


def html_to_text(text: str) -> str:
    return BeautifulSoup(text or "", "html.parser").get_text("\n", strip=True)


def in_zone(city: str, postal_code: str) -> bool:
    if postal_code:
        return postal_code[:2] in ZONE_DEPARTMENTS
    return bool(ZONE_CITY_PATTERN.search(city or ""))


def contract_type(title: str, internship_level: bool) -> str:
    if WORK_STUDY_TITLE.search(title):
        return "work-study"
    if JUNIOR_TITLE.search(title) or internship_level:
        return "internship"
    return "not specified"


def remote_work(remote, hybrid) -> str:
    if remote:
        return "full remote"
    if hybrid:
        return "hybrid"
    return "not specified"


def from_smartrecruiters(board: str, job: dict) -> dict:
    location = job.get("location") or {}
    level = (job.get("experienceLevel") or {}).get("id") == "internship"
    level = level or (job.get("typeOfEmployment") or {}).get("id") == "intern"
    return {"id": str(job.get("id") or ""), "title": job.get("name") or "", "internship_level": level,
            "city": location.get("city") or "", "postal_code": location.get("postalCode") or "",
            "remote_work": remote_work(location.get("remote"), location.get("hybrid")),
            "published_date": (job.get("releasedDate") or "")[:10]}


def from_greenhouse(board: str, job: dict) -> dict:
    content = BeautifulSoup(html.unescape(job.get("content") or ""), "html.parser")
    for generic in content.select(".content-intro, .content-conclusion, .content-pay-transparency"):
        generic.decompose()  # text about the company, the same for every offer: not useful, costs tokens
    return {"id": str(job.get("id") or ""), "title": job.get("title") or "", "internship_level": False,
            "city": (job.get("location") or {}).get("name") or "", "postal_code": "", "remote_work": "not specified",
            "published_date": (job.get("first_published") or job.get("updated_at") or "")[:10],
            "description": content.get_text("\n", strip=True)}


def from_lever(board: str, job: dict) -> dict:
    categories = job.get("categories") or {}
    created = job.get("createdAt")
    published = datetime.datetime.fromtimestamp(created / 1000).date().isoformat() if isinstance(created, int) else ""
    lists = "\n\n".join(f"{item.get('text', '')}\n{html_to_text(item.get('content'))}" for item in job.get("lists") or [])
    workplace = job.get("workplaceType") or ""
    return {"id": job.get("id") or "", "title": job.get("text") or "", "internship_level": False,
            "city": " / ".join(categories.get("allLocations") or [categories.get("location") or ""]), "postal_code": "",
            "remote_work": remote_work(workplace == "remote", workplace == "hybrid"),
            "published_date": published,
            "description": "\n\n".join(p for p in (job.get("descriptionPlain"), lists, job.get("additionalPlain")) if p)}


def from_ashby(board: str, job: dict) -> dict:
    postal = ((job.get("address") or {}).get("postalAddress") or {})
    cities = [job.get("location") or ""] + [s.get("location") or "" for s in job.get("secondaryLocations") or []]
    workplace = (job.get("workplaceType") or "").lower()
    return {"id": job.get("id") or "", "title": job.get("title") or "", "internship_level": False,
            "city": " / ".join(c for c in cities if c), "postal_code": postal.get("postalCode") or "",
            "remote_work": remote_work(workplace == "remote" or job.get("isRemote"), workplace == "hybrid"),
            "published_date": (job.get("publishedAt") or "")[:10],
            "description": job.get("descriptionPlain") or ""}


PARSERS = {"smartrecruiters": from_smartrecruiters, "greenhouse": from_greenhouse,
           "lever": from_lever, "ashby": from_ashby}


@logs_url  # writes the URL in data/returned_urls.jsonl, for scripts/check_links.py
def common_format(offer: dict) -> dict:
    """Offer of an ATS → common format (§4 of docs/ARCHITECTURE.md)."""
    title = offer["title"] or "not specified"
    description = offer.get("description") or ""
    return {
        "id": offer["common_id"],
        "source": f"ats_{offer['provider']}",
        "title": title,
        "company": COMPANY_OF[(offer["provider"], offer["board"])],
        "city": offer["city"] or "not specified",
        "postal_code": offer["postal_code"] or "not specified",
        "contract_type": contract_type(title, offer["internship_level"]),
        "duration": "not specified",   # only in the description
        "start_date": "not specified",
        "remote_work": offer["remote_work"],
        "published_date": offer["published_date"] or "not specified",
        "url": PUBLIC_URL[offer["provider"]].format(board=offer["board"], id=offer["id"]),
        "description": description.strip(),
        "score_bonus": offer_bonus(title, description),  # points for the agent to add at the end (mcp/score_bonus.py)
    }


async def read_board(provider: str, board: str) -> list[dict]:
    """All the offers of one company (raw fields of PARSERS). Raises RuntimeError on error."""
    url = LIST_URL[provider].format(board=board)
    if provider != "smartrecruiters":
        data = await client.get_json(url)
        jobs = data if provider == "lever" else data.get("jobs", [])
        return [PARSERS[provider](board, job) for job in jobs if isinstance(job, dict)]
    jobs = []
    for page in range(SR_MAX_PAGES):
        data = await client.get_json(url, {"country": "fr", "limit": SR_PAGE_SIZE, "offset": page * SR_PAGE_SIZE})
        content = data.get("content") or []
        jobs += [PARSERS[provider](board, job) for job in content if isinstance(job, dict)]
        if len(content) < SR_PAGE_SIZE:
            break
    return jobs


mcp = MCPServer(
    "ats",
    instructions="Internship and work-study offers from the career pages (ATS) of a few companies. "
                 "Call search_offers once, then get_offer_details for the new offers.",
)


@mcp.tool()
async def search_offers(published_since_days: int = 31) -> dict:
    """Read the career pages of the companies set in the configuration.
    No keyword, no place: the code keeps only internships and work-study offers in the zone of the
    configuration. Call it ONCE per run (about 1 minute).

    Returns a SHORT list (id, title, company, city, contract_type, published_date), without duplicates.
    To read a full offer, call get_offer_details next.
    """
    global client
    if not BOARDS:
        raise ToolError(missing_config("ats"))
    client = client or AtsClient()
    if not 1 <= published_since_days <= 60:
        raise ToolError("published_since_days must be between 1 and 60.")
    oldest = (datetime.date.today() - datetime.timedelta(days=published_since_days)).isoformat()

    offers, errors = {}, []
    counts = {"read": 0, "not_junior": 0, "title": 0, "outside_zone": 0, "old": 0, "senior": 0}
    for name, (provider, board) in BOARDS.items():
        try:
            jobs = await read_board(provider, board)
        except (RuntimeError, httpx.HTTPError) as error:  # lose this company only
            errors.append(f"{name}: {error if isinstance(error, RuntimeError) else type(error).__name__}")
            continue
        for job in jobs:
            counts["read"] += 1
            if not job["id"] or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", job["id"]):
                continue
            if not (JUNIOR_TITLE.search(job["title"]) or job["internship_level"]):
                counts["not_junior"] += 1
            elif not JOB_TITLE.search(job["title"]):
                counts["title"] += 1
            elif not in_zone(job["city"], job["postal_code"]):
                counts["outside_zone"] += 1
            elif job["published_date"] and job["published_date"] < oldest:
                counts["old"] += 1
            elif is_senior_title(job["title"]):
                counts["senior"] += 1
            else:
                common_id = f"ats:{provider}:{board}:{job['id']}"
                CACHE[common_id] = {**job, "provider": provider, "board": board, "common_id": common_id}
                offers[common_id] = common_format(CACHE[common_id])

    short_fields = ("id", "title", "company", "city", "contract_type", "published_date")
    return {
        "companies_read": len(BOARDS) - len(errors),
        "requests_sent": client.request_count,
        "offers_read": counts["read"],
        "offer_count": len(offers),
        "skipped_not_internship": counts["not_junior"],
        "skipped_by_title": counts["title"],
        "skipped_outside_zone": counts["outside_zone"],
        "old_skipped": counts["old"],
        "skipped_senior_title": counts["senior"],
        "offers": [{k: v for k, v in o.items() if k in short_fields} for o in offers.values()],
        "errors": errors,
    }


@mcp.tool()
async def get_offer_details(ids: list[str]) -> list[dict]:
    """Return the full offers (common format, with the description) for these ids.

    ids in the format "ats:{ats}:{board}:{id}", returned by search_offers. At most 5 ids per call,
    and 40 detail requests per run: choose the titles closest to my jobs first, then the most recent.
    """
    global client, details_count
    if len(ids) > MAX_DETAILS:
        raise ToolError(f"At most {MAX_DETAILS} ids per call. Split the list and call several times.")
    client = client or AtsClient()
    offers = []
    for common_id in ids:
        valid = ID_PATTERN.fullmatch(common_id)
        if not valid or (valid.group(1), valid.group(2)) not in COMPANY_OF:
            offers.append({"id": common_id, "error": "invalid id: use an id returned by search_offers of this server"})
            continue
        offer = CACHE.get(common_id)
        # Not in the cache (apply.sh starts a new server) or no description yet (SmartRecruiters list): ask the ATS.
        if offer is None or "description" not in offer:
            if details_count >= MAX_DETAILS_PER_RUN:
                offers.append({"id": common_id, "error": f"limit of {MAX_DETAILS_PER_RUN} details per run reached"})
                continue
            details_count += 1
            try:
                offer = await fetch_offer(*valid.groups())
            except (RuntimeError, httpx.HTTPError) as error:
                offers.append({"id": common_id, "error": f"{error or type(error).__name__}: offer not found or expired"})
                continue
            if offer is None:
                offers.append({"id": common_id, "error": "offer not found: expired or removed by the company"})
                continue
            CACHE[common_id] = offer
        offers.append(common_format(offer))
    return offers


async def fetch_offer(provider: str, board: str, job_id: str) -> dict | None:
    """One full offer, asked to the ATS (raw fields of PARSERS + description), or None if it does not exist."""
    if provider == "smartrecruiters":
        data = await client.get_json(SR_DETAIL_URL.format(board=board, id=job_id))
        job = from_smartrecruiters(board, data)
        sections = (data.get("jobAd") or {}).get("sections") or {}
        # companyDescription is left out: the same text for every offer of the company.
        parts = [f"{s.get('title') or ''}\n{html_to_text(s.get('text'))}"
                 for key, s in sections.items() if key != "companyDescription" and isinstance(s, dict)]
        job["description"] = "\n\n".join(p.strip() for p in parts if p.strip())
    elif provider == "ashby":  # no route for one offer: read the list again
        job = next((j for j in await read_board(provider, board) if j["id"] == job_id), None)
    else:
        job = PARSERS[provider](board, await client.get_json(DETAIL_URL[provider].format(board=board, id=job_id)))
    if not job or job["id"] != job_id:
        return None
    return {**job, "provider": provider, "board": board, "common_id": f"ats:{provider}:{board}:{job_id}"}


async def manual_test() -> None:
    """Small test without Claude: all the companies, then the details of the first offer."""
    result = await search_offers()
    print(f"{'✅' if result['offer_count'] else '❌'} {result['offer_count']} offers out of {result['offers_read']} read, "
          f"errors: {result['errors'] or 'none'}")
    print(f"   skipped: {result['skipped_not_internship']} not internship, {result['skipped_by_title']} by title, "
          f"{result['skipped_outside_zone']} outside zone, "
          f"{result['old_skipped']} old, {result['skipped_senior_title']} senior")
    for offer in result["offers"][:40]:
        print(f"   - {offer['published_date']} | {offer['title'][:60]} | {offer['company']} | {offer['city']} | {offer['contract_type']}")
    if result["offers"]:
        detail = (await get_offer_details([result["offers"][0]["id"]]))[0]
        print(f"{'✅' if detail.get('description') else '❌'} Details of the 1st offer: "
              f"{len(detail.get('description', ''))} characters, url: {detail.get('url')}, error: {detail.get('error')}")
    print(f"Requests sent: {client.request_count}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        asyncio.run(manual_test())
    else:
        mcp.run()
