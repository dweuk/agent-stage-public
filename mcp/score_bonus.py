"""Score bonus and senior filter computed by the code, shared by the MCP servers that read offers.

Bonus rules (the servers put the sum in the field `score_bonus` of each full offer; the agent only adds it
at the end of the scoring, see step 5 of the skill. To change a bonus, edit it here):
- an offer that mentions a school agreement ("convention de stage"), because I am in a school and can sign one;
- an offer that says it accepts both an internship and a work-study contract ("stage ou alternance").

Filter: `is_senior_title` tells the servers to leave out the offers whose title asks for a senior profile.
"""

import re

CONVENTION_BONUS = 1.5  # points out of 10, added after the caps and the penalties (the score never goes over 10)

MIXED_CONTRACT_BONUS = 2.0  # points out of 10, same rule: added at the end, the score never goes over 10

SENIOR_TITLE_PATTERN = re.compile(r"\bs[ée]nior\b|\bconfirm[ée]e?\b|\bexp[ée]riment[ée]e?\b", re.IGNORECASE)
MIXED_CONTRACT_PATTERN = re.compile(r"\bstage\s*(?:et|ou|/|-|,|&)\s*(?:en\s+)?alternance\b|\balternance\s*(?:et|ou|/|-|,|&)\s*(?:un\s+)?stage\b",
                                    re.IGNORECASE)
CONVENTION_PATTERN = re.compile(r"convention\s+de\s+stage|stage\s+conventionn[ée]|conventionn[ée]e?\s+avec\s+(?:votre|ton|une)\s+(?:école|ecole)",
                                re.IGNORECASE)
NEGATION_BEFORE = re.compile(r"(?:sans|pas\s+de|hors|aucune)\s+$", re.IGNORECASE)


def convention_bonus(description: str) -> float:
    """CONVENTION_BONUS if the text mentions a school agreement (and does not say "sans convention de stage"), else 0."""
    for found in CONVENTION_PATTERN.finditer(description or ""):
        if not NEGATION_BEFORE.search(description[max(0, found.start() - 12):found.start()]):
            return CONVENTION_BONUS
    return 0.0


def mixed_contract_bonus(title: str, description: str) -> float:
    """MIXED_CONTRACT_BONUS if the title or the text says "stage ou alternance" (or the other way round), else 0."""
    if MIXED_CONTRACT_PATTERN.search(f"{title or ''}\n{description or ''}"):
        return MIXED_CONTRACT_BONUS
    return 0.0


def offer_bonus(title: str, description: str) -> float:
    """All the bonuses of one offer, in points out of 10."""
    return convention_bonus(description) + mixed_contract_bonus(title, description)


def is_senior_title(title: str) -> bool:
    """True if the title asks for a senior profile ("senior", "confirmé", "expérimenté")."""
    return bool(SENIOR_TITLE_PATTERN.search(title or ""))
