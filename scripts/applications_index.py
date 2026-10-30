"""Offers of a report for scripts/apply_all.sh, and the mails.md that joins all their emails.

apply_all.sh puts the drafts of a report in applications/<report name>/parts/, one folder per offer: NN-company/
(NN = rank in the report). This script:
- `list`: prints one line per offer of the "## Top" section, for the loop of apply_all.sh:
  num<US>title<US>company<US>link<US>folder<US>state (US = \x1f, the ASCII "unit separator")
  Not a tab: for bash `read`, a tab is white space, so two tabs in a row (an empty field) count as one
  and the next fields move. \x1f is not white space, and clean() removes it from the fields.
  state = applied (an application is in my tracking: no draft), done (a valid draft exists), todo.
- `mails`: writes <base>/mails.md (in French: it is for me): all the emails to check, with the same headings,
  then the offers with no email here: DANGER, not done or failed, already sent.
- `clean`: deletes <base>/parts/ when mails.md holds everything (no offer is DANGER, not done or failed).

The report is written by the agent from offer texts: every field is untrusted. Tabs, new lines and control
characters are removed, folder names keep only a-z 0-9 and "-", and the fields written by this script in mails.md
show no HTML and only https links (the drafts themselves are checked by apply.sh: a DANGER draft is never copied).
The memory database is opened read-only (MEMORY_DB lets the tests use another file).

Usage (done by apply_all.sh):
    .venv/bin/python scripts/applications_index.py list  reports/2026-10-28.md applications/2026-10-28
    .venv/bin/python scripts/applications_index.py mails reports/2026-10-28.md applications/2026-10-28
    .venv/bin/python scripts/applications_index.py clean reports/2026-10-28.md applications/2026-10-28
"""

import datetime
import os
import re
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the agent-stage-public/ folder
DB_PATH = Path(os.environ.get("MEMORY_DB", ROOT / "data" / "offers.db"))

# The only headings of a draft, in this order (skill prepare-application, file *-mail.md).
MAIL_HEADINGS = ["### Offre", "### Destinataire", "### Manque", "### À vérifier et points importants", "### Mail"]
HEADING = re.compile(r"^#+[ \t].*$", re.MULTILINE)
MAILS_NAME = "mails.md"
PARTS_NAME = "parts"
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
SAFE_LINK = re.compile(r"https://[^\s<>()|\"'`\\]+")
OFFER_LINE = re.compile(r"^### (\d+)\. (.*)$")
FIELD_SEPARATOR = "\x1f"  # between the fields of `list` (see the docstring)


def clean(text: str) -> str:
    """One line of plain text: no tab, no new line, no control character."""
    return CONTROL_CHARS.sub(" ", text).strip()


def slug(company: str) -> str:
    """Folder-safe company name: "Société Générale (Lyon)" → "societe-generale-lyon"."""
    ascii_name = unicodedata.normalize("NFKD", company).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:40].strip("-")
    return name or "offre"


def parse_report(report: Path) -> list[dict]:
    """The offers of the "## Top" section: "### N. Title — Company", then rows like "| Lien | url |"."""
    offers = []
    in_top = False
    for line in report.read_text().splitlines():
        if line.startswith("## "):
            in_top = line.startswith("## Top")
            continue
        if not in_top:
            continue
        match = OFFER_LINE.match(line)
        if match:
            num, rest = match.groups()
            # The company is after the LAST " — ": a title can contain one too.
            title, _, company = rest.rpartition(" — ") if " — " in rest else (rest, "", "")
            offers.append({"num": int(num), "title": clean(title), "company": clean(company),
                           "link": "", "contract": "", "score": ""})
        elif offers and line.startswith("**Note :"):
            offers[-1]["score"] = clean(line.strip("*").removeprefix("Note :"))
        elif offers and line.startswith("| "):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] == "Lien":
                offers[-1]["link"] = clean(cells[1])
            elif len(cells) >= 2 and cells[0] == "Contrat":
                offers[-1]["contract"] = clean(cells[1])
    for offer in offers:
        offer["folder"] = f"{PARTS_NAME}/{offer['num']:02d}-{slug(offer['company'])}"
    return offers


def applied_offers(offers: list[dict]) -> set[int]:
    """Numbers of the offers with an "application" row in my tracking (read-only, never written here).

    Match by offer id (found with the link of the report), or by company when the tracking row has no offer id.
    """
    if not DB_PATH.is_file():
        return set()
    try:
        db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            rows = db.execute("SELECT company, offer_id FROM tracking WHERE type = 'application'").fetchall()
            ids_by_url = dict(db.execute("SELECT url, id FROM offers WHERE url IS NOT NULL").fetchall())
        finally:
            db.close()
    except sqlite3.Error as error:
        print(f"Warning: cannot read the tracking ({error}): no offer is skipped as already applied.",
              file=sys.stderr)
        return set()
    applied_ids = {offer_id for _, offer_id in rows if offer_id}
    applied_companies = {company.casefold() for company, offer_id in rows if company and not offer_id}
    return {offer["num"] for offer in offers
            if ids_by_url.get(offer["link"]) in applied_ids or offer["company"].casefold() in applied_companies}


def has_mail_headings(text: str) -> bool:
    """True if the text has exactly the headings of a draft, and starts with the first one."""
    text = unicodedata.normalize("NFC", text).strip()
    return [line.strip() for line in HEADING.findall(text)] == MAIL_HEADINGS and text.startswith(MAIL_HEADINGS[0])


def mail_draft(folder: Path) -> Path | None:
    """The newest valid draft of the folder. A draft with other headings does not count: the offer is run again."""
    drafts = [path for path in folder.glob("*-mail*.md") if has_mail_headings(path.read_text())]
    return max(drafts, key=lambda path: path.stat().st_mtime, default=None)


def last_status(base: Path) -> dict[int, str]:
    """Last result of each offer in <base>/status.tsv (written by apply_all.sh): ok, danger or failed."""
    status = {}
    path = base / "status.tsv"
    if path.is_file():
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].isdigit():
                status[int(parts[0])] = parts[1]
    return status


def state_of(offer: dict, base: Path, applied: set[int]) -> str:
    if offer["num"] in applied:
        return "applied"
    return "done" if mail_draft(base / offer["folder"]) else "todo"


def cell(text: str) -> str:
    """Text for a Markdown table cell: no "|", and no HTML (a Markdown preview would render it)."""
    return text.replace("|", "/").replace("<", "‹").replace(">", "›") or "—"


def link_cell(link: str) -> str:
    return f"<{link}>" if SAFE_LINK.fullmatch(link) else "lien invalide (ne pas ouvrir)"


def group_offers(report: Path, base: Path) -> dict[str, list[dict]]:
    """The offers of the report sorted by what I must do: todo (to check), sent, danger, failed.
    """
    offers = parse_report(report)
    applied = applied_offers(offers)
    status = last_status(base)
    groups = {"todo": [], "sent": [], "danger": [], "failed": []}
    for offer in offers:
        state = state_of(offer, base, applied)
        if state == "applied":
            groups["sent"].append(offer)
        elif status.get(offer["num"]) == "danger":
            groups["danger"].append(offer)
        elif state == "done":
            groups["todo"].append(offer)
        else:
            groups["failed"].append(offer)
    return groups


def keywords_section(folder: Path) -> list[str]:
    """The keywords.md of an offer, for mails.md. If the agent changed this file, apply.sh checked it (DANGER)."""
    path = folder / "keywords.md"
    if not path.is_file():
        return []
    # Without its title, and with no heading: the headings of an offer in mails.md stay the same.
    lines = path.read_text().strip().splitlines()[1:]
    return ["### Mots-clés (calculés par le code)", *[re.sub(r"^#+[ \t]+(.*)$", r"**\1**", line) for line in lines], ""]


def write_mails(report: Path, base: Path) -> Path:
    """Write <base>/mails.md: every email to check, with the same headings, then the offers without email.

    The DANGER drafts are never copied here: one image or link in them would make the whole file unsafe to preview.
    Once parts/ is deleted (see clean_parts), mails.md is the only copy of the emails: it is never rewritten.
    """
    mails = base / MAILS_NAME
    if mails.is_file() and not (base / PARTS_NAME).is_dir():
        print(f"Emails: {mails} is finished ({PARTS_NAME}/ was deleted), not rewritten.")
        return mails
    groups = group_offers(report, base)

    def table(rows: list[dict]) -> list[str]:
        if not rows:
            return ["Aucune.", ""]
        lines = ["| # | Note | Contrat | Offre | Entreprise | Dossier | Lien |", "|---|---|---|---|---|---|---|"]
        for offer in rows:
            lines.append(f"| {offer['num']} | {cell(offer['score'])} | {cell(offer['contract'])} "
                         f"| {cell(offer['title'])} | {cell(offer['company'])} | `{offer['folder']}/` "
                         f"| {link_cell(offer['link'])} |")
        return lines + [""]

    def mail_section(offer: dict) -> list[str]:
        draft = mail_draft(base / offer["folder"]).read_text().strip()
        facts = (f"- Note : {cell(offer['score'])} · Contrat : {cell(offer['contract'])} "
                 f"· Lien : {link_cell(offer['link'])}")
        # The first line of a draft is always "### Offre" (checked by mail_draft).
        heading, _, rest = draft.partition("\n")
        return [f"## {offer['num']}. {cell(offer['title'])} — {cell(offer['company'])}", "",
                heading, facts, "", rest.lstrip("\n"), "", *keywords_section(base / offer["folder"])]

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Mails de candidature — {cell(report.name)}",
        "",
        f"Mis à jour le {now}. **Brouillons seulement : rien n'a été envoyé.** Toutes les offres : `{cell(str(report))}`.",
        "",
        f"**{len(groups['todo'])} à vérifier**, {len(groups['danger'])} DANGER, "
        f"{len(groups['failed'])} pas faites ou en échec, {len(groups['sent'])} déjà envoyées (détails en fin de fichier).",
        "",
        "Pour chaque offre :",
        "1. Lis « Manque » et « À vérifier et points importants » : contrôle chaque ligne avec ton CV.",
        "2. Corrige le mail, et complète le destinataire si c'est `[adresse à compléter]`.",
        "3. Ouvre le lien, vérifie que l'offre existe encore, joins `profile/cv.pdf` et envoie toi-même.",
        "4. Note l'envoi : `./scripts/track.sh \"j'ai postulé chez <entreprise>\"`.",
        "",
    ]
    for offer in groups["todo"]:
        lines += mail_section(offer)
    lines += [
        f"## ⚠️ DANGER : lire en texte brut, jamais en aperçu Markdown ({len(groups['danger'])})",
        "",
        "Le script a trouvé une image, une balise HTML ou un lien absent de ton CV (voir le terminal). "
        "Ces mails ne sont pas copiés ici : ouvre leur dossier dans un éditeur de texte, supprime-le puis relance si besoin.",
        "",
        *table(groups["danger"]),
        f"## Pas encore faites ou en échec : relance `./scripts/apply_all.sh {cell(str(report))}` "
        f"({len(groups['failed'])})",
        "",
        *table(groups["failed"]),
        f"## Déjà envoyées (dans ton suivi) ({len(groups['sent'])})",
        "",
        *table(groups["sent"]),
    ]
    mails.write_text("\n".join(lines))
    print(f"Emails: {mails} — {len(groups['todo'])} to check, {len(groups['danger'])} DANGER, "
          f"{len(groups['failed'])} not done or failed, {len(groups['sent'])} already sent.")
    return mails


def clean_parts(report: Path, base: Path) -> bool:
    """Delete <base>/parts/ if mails.md holds everything. Kept for a DANGER draft (read there), or to finish the run."""
    parts = base / PARTS_NAME
    if not parts.is_dir() or not (base / MAILS_NAME).is_file():
        return False
    groups = group_offers(report, base)
    if groups["danger"] or groups["failed"]:
        print(f"Working files kept in {parts}: {len(groups['danger'])} DANGER, "
              f"{len(groups['failed'])} not done or failed.")
        return False
    shutil.rmtree(parts)
    print(f"Working files deleted ({parts}): everything is in {base / MAILS_NAME}.")
    return True


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in ("list", "mails", "clean"):
        sys.exit("Usage: applications_index.py list|mails|clean <report.md> <output folder>")
    command, report, base = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if command == "mails":
        write_mails(report, base)
        return
    if command == "clean":
        clean_parts(report, base)
        return
    offers = parse_report(report)
    applied = applied_offers(offers)
    for offer in offers:
        fields = (str(offer["num"]), offer["title"], offer["company"], offer["link"], offer["folder"],
                  state_of(offer, base, applied))
        print(FIELD_SEPARATOR.join(fields))


if __name__ == "__main__":
    main()
