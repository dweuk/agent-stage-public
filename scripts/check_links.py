"""Check the links of a report for traps. Run it by hand AFTER a search, before clicking anything.

    .venv/bin/python scripts/check_links.py                      # the newest file of reports/
    .venv/bin/python scripts/check_links.py reports/2026-10-27.md
    .venv/bin/python scripts/check_links.py reports/2026-10-27.md --resolve

Each link is also compared with the log of the URLs returned by the MCP servers (data/returned_urls.jsonl,
written by mcp/returned_urls.py). A link that no server returned is DANGER: the agent invented it or copied it
from the text of an offer (prompt injection). Indeed links are not checked this way: Indeed is a claude.ai
connector, no code of mine sees its URLs. For a test report (reports/test-*.md), the URLs of
tests/fake_offers.json count as returned.

Each link gets a level:
  OK      trusted host (TRUSTED_HOSTS), https, no trick.
  CHECK   unknown host (many offers link to the site of the company): no trick found, but look at the host.
  DANGER  a trick: http, "user@host", IP address, look-alike letters (xn--), a trusted name inside another
          domain ("indeed.com.evil.xyz"), a link shortener, or a redirect parameter. Or a link that no server
          returned (see above). Do not click.

The text of the report is checked too: a Markdown image, an HTML tag or attribute that loads something,
a "javascript:" / "data:" link or a "//host" link gives a DANGER line (a preview can open them without a click).

Without --resolve the script makes NO network call: it only reads the text.
With --resolve it follows the short links of TRUSTED_SHORTENERS (to.indeed.com), 3 redirects at most, with
HEAD requests (no page is downloaded, no cookie kept), and shows where they end. A link that ends on an
untrusted host becomes DANGER. DANGER links are never opened.
Exit code: 1 if there is at least one DANGER link, 2 if there is no report to read, else 0.
"""

import ipaddress
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]  # the agent-stage-public/ folder
sys.path.insert(0, str(ROOT / "mcp"))
from returned_urls import load_urls  # noqa: E402

FAKE_OFFERS = ROOT / "tests" / "fake_offers.json"

# A host is trusted if it IS one of these or ENDS with "." + one of these.
TRUSTED_HOSTS = (
    "indeed.com",
    "francetravail.fr",           # La bonne alternance also links to its partners: France Travail, HelloWork, Meteojob
    "pole-emploi.fr",
    "apprentissage.beta.gouv.fr",
    "labonnealternance.apprentissage.beta.gouv.fr",
    "hellowork.com",
    "meteojob.com",
    "jobs.smartrecruiters.com",   # the 4 ATS of mcp/ats/server.py
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
)
TRUSTED_SHORTENERS = ("to.indeed.com",)   # short links that --resolve may follow
INDEED_HOST = "indeed.com"   # no log for Indeed (claude.ai connector): its links skip the server check
# Names that a fake site likes to copy. Seen in a host that is not trusted → DANGER.
BRAND_WORDS = ("indeed", "francetravail", "pole-emploi", "labonnealternance", "hellowork", "meteojob",
               "smartrecruiters", "greenhouse", "ashbyhq")
OTHER_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "rb.gy", "lnkd.in")
REDIRECT_PARAMS = ("url", "redirect", "redirect_url", "redirect_uri", "next", "continue", "dest", "target", "u")
# A URL scheme ignores case in a browser: "HTTPS://host" is a link too.
URL_PATTERN = re.compile(r"https?://[^\s)>\]\"'<]+", re.IGNORECASE)
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Things in the text of the report that a Markdown preview loads or runs by itself (no click needed),
# or links that are not web pages. The report template uses only <details> and <summary>: they stay allowed.
CONTENT_TRAPS = (
    (re.compile(r"!\["), "Markdown image (a preview loads it at once: its URL can carry data)"),
    (re.compile(r"<(img|a|iframe|frame|script|link|meta|base|object|embed|svg|math|style|form|input|video|audio"
                r"|source|track|picture|body|table)(\s|/|>|$)", re.IGNORECASE), "HTML tag that loads or runs something"),
    (re.compile(r"(^|[^a-z])(src|srcset|href|poster|background|action|formaction)\s*=", re.IGNORECASE),
     "HTML attribute that loads something"),
    (re.compile(r"\]\(\s*<?\s*(javascript|data|vbscript|file):", re.IGNORECASE), "link that is not a web page"),
    (re.compile(r"(^|[(\s\"'=])//[a-z0-9-]+\.[a-z]", re.IGNORECASE), "link without https (\"//host\")"),
)
MAX_REDIRECTS = 3
TIMEOUT = 10


def printable(text: str) -> str:
    """Text of a report, for the terminal: no control character (no terminal escape code)."""
    return CONTROL_CHARS.sub(" ", text)


def look_alike(text: str) -> str:
    """Write the letters that are easy to confuse in the same way: 'lndeed' and 'indeed' become equal."""
    return text.replace("rn", "m").translate(str.maketrans({"1": "i", "l": "i", "0": "o"}))


def is_trusted(host: str) -> bool:
    return any(host == t or host.endswith("." + t) for t in TRUSTED_HOSTS)


def tricks(url: str) -> list[str]:
    """Return the list of tricks found in the text of the URL (empty list = none)."""
    found = []
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        found.append("not https")
    if parts.username is not None or "@" in parts.netloc:
        found.append("contains '@' (the real host is after it)")
    try:
        ipaddress.ip_address(host)
        found.append("the host is an IP address")
    except ValueError:
        pass
    if "xn--" in host or not host.isascii():
        found.append("look-alike letters in the host (punycode)")
    if not is_trusted(host) and any(word in host for word in BRAND_WORDS):
        found.append("a trusted name inside another domain")
    elif not is_trusted(host) and any(look_alike(word) in look_alike(host) for word in BRAND_WORDS):
        found.append("looks like a trusted name with swapped letters (e.g. 'lndeed')")
    if any(host == s or host.endswith("." + s) for s in OTHER_SHORTENERS):
        found.append("link shortener: the real destination is hidden")
    for name, values in parse_qs(parts.query).items():
        if name.lower() in REDIRECT_PARAMS and any(v.startswith(("http://", "https://", "//")) for v in values):
            found.append(f"redirect parameter '{name}' points to another site")
    return found


def known_urls(report: Path) -> set[str] | None:
    """The URLs returned by the servers (and by the fake offers for a test report). None if there is no log."""
    urls = load_urls()
    if report.name.startswith("test"):
        fake = {o["url"] for o in json.loads(FAKE_OFFERS.read_text())} if FAKE_OFFERS.is_file() else set()
        urls = (urls or set()) | fake
    return urls


def resolve(url: str) -> tuple[str, str | None]:
    """Follow a short link with HEAD requests. Returns (last url, problem or None)."""
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                response = client.head(url)
            except httpx.HTTPError as error:
                return url, f"no answer ({type(error).__name__})"
            location = response.headers.get("location")
            if not 300 <= response.status_code < 400 or not location:
                return url, None
            url = str(httpx.URL(url).join(location))
            if tricks(url) or not is_trusted((urlsplit(url).hostname or "").lower()):
                return url, "ends on a host that is not trusted"
        return url, f"more than {MAX_REDIRECTS} redirects"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_resolve = "--resolve" in sys.argv
    if args:
        report = Path(args[0])
    else:
        reports = sorted((ROOT / "reports").glob("*.md"), key=lambda p: p.stat().st_mtime)
        if not reports:
            print("No report found in reports/.", file=sys.stderr)
            return 2
        report = reports[-1]
    if not report.is_file():
        print(f"File not found: {report}", file=sys.stderr)
        return 2

    text = report.read_text()
    urls = list(dict.fromkeys(m.group(0).rstrip(".,;") for m in URL_PATTERN.finditer(text)))
    print(f"{report}: {len(urls)} different links\n")
    returned = known_urls(report)
    if returned is None:
        print("⚠ No log of the server URLs yet (data/returned_urls.jsonl): links not compared with the servers.\n")
    danger = 0
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern, reason in CONTENT_TRAPS:
            if pattern.search(line):
                danger += 1
                print(f"DANGER line {number}: {reason}\n       {printable(line.strip()[:110])}")
    if danger:
        print("       ⚠ Do NOT open this report in a Markdown preview: read it as plain text.\n")
    for url in urls:
        host = (urlsplit(url).hostname or "").lower()
        problems = tricks(url)
        note = ""
        is_indeed = host == INDEED_HOST or host.endswith("." + INDEED_HOST)
        if returned is not None and not is_indeed and url not in returned:
            problems.append("no server returned this link: invented, or copied from the text of an offer")
        if not problems and do_resolve and host in TRUSTED_SHORTENERS:
            last, problem = resolve(url)
            if problem:
                problems.append(problem)
            note = f"  → ends on {urlsplit(last).hostname}"
        if problems:
            level, danger = "DANGER", danger + 1
        elif is_trusted(host):
            level = "OK"
        else:
            level = "CHECK"
        print(printable(f"{level:6} {host}{note}") + f"\n       {printable(url[:110])}")
        for problem in problems:
            print(f"       ⚠ {printable(problem)}")
    print(f"\n{danger} DANGER link(s)." if danger else "\nNo DANGER link.")
    return 1 if danger else 0


if __name__ == "__main__":
    sys.exit(main())
