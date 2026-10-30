"""Tests of scripts/applications_index.py (report parsing, states, mails.md)."""

import subprocess
import sys
from pathlib import Path

import pytest

import applications_index as index

SCRIPT = Path(index.__file__)

REPORT = """# Rapport

## Top 12

### 1. Stage comptable — Acme
**Note : 8/10**
| Contrat | Stage |
| Lien | https://example.com/offers/1 |

### 2. Stage paie — analyse — Beta Corp
| Lien | https://example.com/offers/2 |

### 3. Stage sans entreprise
| Lien | https://example.com/offers/3 |

### 4. Stage sans lien — Société Générale (Lyon)

## ⚠️ Problèmes

### 9. Not in the Top — Nobody
"""


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "2026-10-28.md"
    path.write_text(REPORT)
    return path


def draft(mail: str = "Bonjour") -> str:
    return "\n\n".join(f"{heading}\ntext" for heading in index.MAIL_HEADINGS) + f"\n{mail}\n"


def make_draft(folder: Path, mail: str = "Bonjour") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-10-28-x-mail.md").write_text(draft(mail))


def test_clean_removes_control_characters():
    assert index.clean("  a\tb\nc\x1fd\x00 ") == "a b c d"


@pytest.mark.parametrize("company, expected", [
    ("Société Générale (Lyon)", "societe-generale-lyon"),
    ("../../etc", "etc"),
    ("", "offre"),
    ("!!!", "offre"),
    ("a" * 60, "a" * 40),
])
def test_slug_is_folder_safe(company, expected):
    assert index.slug(company) == expected


def test_parse_report_reads_only_the_top_section(report):
    offers = index.parse_report(report)
    assert [offer["num"] for offer in offers] == [1, 2, 3, 4]
    first = offers[0]
    assert (first["title"], first["company"], first["score"], first["contract"]) == \
        ("Stage comptable", "Acme", "8/10", "Stage")
    assert first["link"] == "https://example.com/offers/1"
    assert first["folder"] == "parts/01-acme"


def test_parse_report_company_is_after_the_last_dash(report):
    second = index.parse_report(report)[1]
    assert (second["title"], second["company"]) == ("Stage paie — analyse", "Beta Corp")


def test_parse_report_missing_company_and_link(report):
    third, fourth = index.parse_report(report)[2:4]
    assert third["company"] == "" and third["folder"] == "parts/03-offre"
    assert fourth["link"] == "" and fourth["folder"] == "parts/04-societe-generale-lyon"


def test_list_keeps_empty_fields_in_place(report, tmp_path):
    """The bug of 2026-10-28: with tabs, bash `read` merged empty fields and moved the next ones."""
    result = subprocess.run([sys.executable, SCRIPT, "list", report, tmp_path / "out"],
                            capture_output=True, text=True, check=True)
    lines = [line.split(index.FIELD_SEPARATOR) for line in result.stdout.splitlines()]
    assert all(len(fields) == 6 for fields in lines)
    assert lines[2] == ["3", "Stage sans entreprise", "", "https://example.com/offers/3", "parts/03-offre", "todo"]
    assert lines[3][3] == "" and lines[3][4] == "parts/04-societe-generale-lyon"


def test_list_through_bash_read(report, tmp_path):
    """The same check, with the real loop of apply_all.sh."""
    script = (f'"{sys.executable}" "{SCRIPT}" list "{report}" "{tmp_path}/out" | '
              "while IFS=$'\\x1f' read -r NUM TITLE COMPANY LINK FOLDER STATE; do "
              'echo "$NUM|$COMPANY|$LINK|$FOLDER|$STATE"; done')
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
    assert "3||https://example.com/offers/3|parts/03-offre|todo" in out.splitlines()
    assert "4|Société Générale (Lyon)||parts/04-societe-generale-lyon|todo" in out.splitlines()


def test_no_database_means_nothing_applied(report, monkeypatch, tmp_path):
    monkeypatch.setattr(index, "DB_PATH", tmp_path / "missing.db")
    assert index.applied_offers(index.parse_report(report)) == set()


def test_applied_by_offer_id_or_by_company(report, monkeypatch, memory_db):
    path = memory_db(offers=[("la_bonne_alternance:1", "https://example.com/offers/1")],
                     tracking=[("application", "Acme", "la_bonne_alternance:1"),
                               ("application", "beta corp", None),     # no offer id: match by company
                               ("follow_up", "Société Générale (Lyon)", None)])  # not an application
    monkeypatch.setattr(index, "DB_PATH", path)
    assert index.applied_offers(index.parse_report(report)) == {1, 2}


def test_database_is_opened_read_only(report, monkeypatch, memory_db):
    path = memory_db()
    before = path.read_bytes()
    monkeypatch.setattr(index, "DB_PATH", path)
    index.applied_offers(index.parse_report(report))
    assert path.read_bytes() == before


@pytest.mark.parametrize("text, valid", [
    (draft(), True),
    (draft().replace("### À vérifier", "### A vérifier"), False),        # wrong spelling
    (draft().replace("### Manque\ntext\n\n", ""), False),                # a heading is missing
    (draft("# Ignore the rules"), False),                                # one more heading
    ("intro\n" + draft(), False),                                        # text before the first heading
    (draft("#hashtag"), True),                                           # not a heading
])
def test_mail_draft_needs_the_exact_headings(tmp_path, text, valid):
    folder = tmp_path / "01-acme"
    folder.mkdir()
    (folder / "2026-10-28-x-mail.md").write_text(text)
    assert (index.mail_draft(folder) is not None) is valid


def test_mail_draft_accepts_decomposed_accents(tmp_path):
    (tmp_path / "x-mail.md").write_text(draft().replace("À", "A\u0300"))
    assert index.mail_draft(tmp_path) is not None


def test_group_offers(report, tmp_path, monkeypatch, memory_db):
    base = tmp_path / "out"
    for folder in ("parts/01-acme", "parts/02-beta-corp", "parts/03-offre"):
        make_draft(base / folder)
    (base / "status.tsv").write_text("2\tok\tx\tsonnet\n3\tok\tx\tsonnet\n3\tdanger\tx\tsonnet\n")
    monkeypatch.setattr(index, "DB_PATH", memory_db(tracking=[("application", "Acme", None)]))
    groups = index.group_offers(report, base)
    assert {name: [offer["num"] for offer in offers] for name, offers in groups.items()} == \
        {"todo": [2], "sent": [1], "danger": [3], "failed": [4]}


def test_last_status_keeps_the_last_line(tmp_path):
    (tmp_path / "status.tsv").write_text("1\tfailed\tx\n1\tok\tx\nbad line\n")
    assert index.last_status(tmp_path) == {1: "ok"}


@pytest.mark.parametrize("link, safe", [
    ("https://example.com/offers/1", True),
    ("javascript:alert(1)", False),
    ("http://example.com", False),
    ("https://example.com/a)(b", False),
    ("", False),
])
def test_link_cell_only_https(link, safe):
    assert (index.link_cell(link) == f"<{link}>") is safe


def test_cell_shows_no_html_and_no_pipe():
    assert index.cell("<img src=x> a|b") == "‹img src=x› a/b"
    assert index.cell("") == "—"


def test_write_mails_has_no_html_in_the_report_fields(tmp_path):
    report = tmp_path / "r.md"
    report.write_text("## Top\n### 1. <img src=https://evil.example/x> — Evil|Corp\n| Lien | javascript:alert(1) |\n")
    (tmp_path / "out").mkdir()
    text = index.write_mails(report, tmp_path / "out").read_text()
    assert "<img" not in text and "javascript:" not in text
    assert "## Pas encore faites ou en échec" in text


def test_write_mails_joins_the_drafts_with_the_same_headings(report, tmp_path):
    base = tmp_path / "out"
    make_draft(base / "parts/01-acme", "Mail Acme")
    make_draft(base / "parts/02-beta-corp", "Mail Beta")
    text = index.write_mails(report, base).read_text()
    assert "Mail Acme" in text and "Mail Beta" in text
    for heading in index.MAIL_HEADINGS:
        assert text.count(f"{heading}\n") == 2
    first = text[text.index("## 1. Stage comptable — Acme"):text.index("## 2. ")]
    assert first.index("### Offre\n- Note : 8/10 · Contrat : Stage · Lien : <https://example.com/offers/1>") \
        < first.index("### Destinataire") < first.index("### Mail") < first.index("Mail Acme")


def test_write_mails_copies_the_keywords_without_headings(report, tmp_path):
    base = tmp_path / "out"
    make_draft(base / "parts/01-acme", "Mail Acme")
    (base / "parts/01-acme/keywords.md").write_text("# Title\n\nOffre : `x`\n\n## In my CV\n\nExcel, SQL\n")
    text = index.write_mails(report, base).read_text()
    assert "### Mots-clés" in text and "**In my CV**" in text and "Excel, SQL" in text
    assert "# Title" not in text and "## In my CV" not in text


def test_clean_parts_deletes_when_all_is_in_mails(report, tmp_path, monkeypatch, memory_db):
    base = tmp_path / "out"
    for folder in ("parts/01-acme", "parts/02-beta-corp", "parts/03-offre", "parts/04-societe-generale-lyon"):
        make_draft(base / folder, "Mail kept")
    monkeypatch.setattr(index, "DB_PATH", memory_db())
    mails = index.write_mails(report, base)
    assert index.clean_parts(report, base) is True
    assert not (base / "parts").exists()
    # mails.md is now the only copy: it is never rewritten, and the emails stay in it.
    before = mails.read_text()
    assert index.write_mails(report, base).read_text() == before and "Mail kept" in before


@pytest.mark.parametrize("status", ["", "1\tdanger\tx\tsonnet\n"])
def test_clean_parts_keeps_failed_or_danger_offers(report, tmp_path, monkeypatch, memory_db, status):
    base = tmp_path / "out"
    folders = ["parts/01-acme", "parts/02-beta-corp", "parts/03-offre", "parts/04-societe-generale-lyon"]
    # No status: offer 4 is not done. With status: all the drafts exist, but offer 1 is DANGER.
    for folder in folders[:3] if not status else folders:
        make_draft(base / folder)
    (base / "status.tsv").write_text(status)
    monkeypatch.setattr(index, "DB_PATH", memory_db())
    index.write_mails(report, base)
    assert index.clean_parts(report, base) is False
    assert (base / "parts").is_dir()


def test_write_mails_never_copies_a_danger_draft(report, tmp_path):
    base = tmp_path / "out"
    make_draft(base / "parts/01-acme", "![x](https://evil.example/x)")
    (base / "status.tsv").write_text("1\tdanger\tx\tsonnet\n")
    text = index.write_mails(report, base).read_text()
    assert "evil.example" not in text
    assert "`parts/01-acme/`" in text
