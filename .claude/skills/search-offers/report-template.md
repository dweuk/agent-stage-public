# Report template

Follow this structure **exactly**: same headings, same order, same fields.
- **Write the report in French.** The headings and labels below are already in French: keep them as they are.
- Replace the `{braces}` with the real values. The text inside the braces is an instruction for you: do not copy it.
- Information missing from the offer → write `non précisé`.
- The offer fields use English values: translate them in the report. `internship` → stage, `work-study` → alternance, `on site` → sur site, `hybrid` → hybride, `full remote` → 100 % à distance, `as soon as possible` → dès que possible, `not specified` → non précisé. A start date like `2028-03-06 (flexible)` → « 6 mars 2028 (date souple) ».
- Names of the sources: `la_bonne_alternance` → La bonne alternance, `ats_smartrecruiters` / `ats_greenhouse` / `ats_lever` / `ats_ashby` → Site carrières (SmartRecruiters / Greenhouse / Lever / Ashby).
- Keep the original title of the offer, even if it is in English.
- Write scores the French way, with a comma: `8,6/10`.
- The example at the end shows a filled-in offer. **Do not copy its content**: it only shows the form.

---

## Structure

```markdown
# Rapport d'offres — {AAAA-MM-JJ}

> Mode : {normal | test}
> Généré le {AAAA-MM-JJ} à {HH:MM} {← the time comes from the request. If it is not given, remove « à {HH:MM} »}

## Résumé

| | Nombre |
|---|---|
| Offres trouvées | {n} |
| Déjà vues (retirées) | {n, or « — » in test mode} |
| Republications (déjà vues sous un autre lien) | {n, or « — » in test mode} |
| Nouvelles offres analysées | {n} |
| Éliminées | {n} |
| Sous le seuil (< 4/10 ou hors des 12 retenues) | {n} |
| **Retenues dans ce rapport** | **{n}** |

**Sources**
| Source | État | Offres trouvées |
|---|---|---|
| {La bonne alternance} | {✅ OK | ❌ erreur : short message | ⏸️ en pause} | {n, or « — » if paused} |
| Indeed | {✅ OK (20/20 recherches) | ⚠️ partiel : {x}/20 recherches, {y} refusées (limite d'appels Indeed) | ❌ erreur : short message} {if details were refused, add « , {z} détails refusés »} | {n} |
{… one row per source of step 2 of the skill, paused sources included …}

{If an error or a problem happened: one sentence per problem, under the heading « ⚠️ Problèmes ». Otherwise, do not add this heading. If Indeed refused calls even after the second try: one sentence that names the lost searches (keyword + place), e.g. « Indeed : recherche « stage {job} » à {place} refusée 2 fois (limite d'appels), ses offres n'ont pas été vues. »}

{If no offer is kept: write « Aucune offre à 4/10 ou plus dans cette recherche. » and go straight to the appendix.}

---

## Top {n} des offres

### 1. {Intitulé de l'offre} — {Entreprise}
**Note : {x}/10**

{Justification: 2-3 sentences in French, based only on the text of the offer.}

| | |
|---|---|
| Contrat | {stage / alternance} — {durée} |
| Début | {date de début} |
| Lieu | {ville} ({code postal}) |
| Mode de travail | {sur site / hybride / non précisé} |
| {name of criterion 3 of criteria.md} | {~x %} {add « (estimation) » if the number is not written in the offer} |
| Publiée le | {AAAA-MM-JJ} |
| Source | {La bonne alternance / Indeed / Site carrières (SmartRecruiters…)} {for La bonne alternance, add the original source of the description in brackets, e.g. « La bonne alternance (Hellowork) »} |
| Lien | {URL exacte} |

**Points forts**
- {strong point linked to my criteria}

**Points faibles**
- {weak point linked to my criteria, or « aucun relevé »}

<details><summary>Détail de la note</summary>

| Critère | Points |
|---|---|
| Type de poste | {x} / 20 |
| {name of criterion 2 of criteria.md} | {x} / 15 |
| {name of criterion 3 of criteria.md} | {x} / 10 |
| {name of criterion 4 of criteria.md} | {x} / 15 |
| Apprentissage | {x} / 15 ({rows counted, e.g. équipe +3, missions variées +3}) |
| Mode de travail | {x} / 5 |
| Dates et durée | {x} / 10 |
| Type de contrat | {x} / 10 |
| Plafond appliqué | {aucun / 30 / 50} |
| Pénalité date de début non précisée | {aucune / −10} |
| Pénalité description absente | {aucune / −40} |
| Pénalité titre senior/chef | {aucune / −30} |
| Pénalité profil senior demandé (texte) | {aucune / −20} |
| Pénalité années d'expérience demandées | {aucune / −10} |
| Bonus (convention de stage, stage et alternance) | {aucun / +x point(s) sur 10, champ `score_bonus`} |
| **Total** | **{x} / 100 → {x,x} / 10** |

</details>

---

{… same block for each kept offer, from the best score to the worst …}

## Annexe : offres écartées

### Éliminées
| Offre | Entreprise | Code | Raison |
|---|---|---|---|
| {title} | {company} | {E1_FULL_REMOTE…} | {one sentence} |

### Sous le seuil
| Offre | Entreprise | Note | Raison principale |
|---|---|---|---|
| {title} | {company} | {x}/10 | {one sentence} |

### Republications
{Offers returned by `find_reposts` (step 3 of the skill): not analysed again. Remove this heading in test mode.}
| Offre | Entreprise | Déjà vue sous | Note de l'époque | Remarque |
|---|---|---|---|---|
| {title} | {company} | {same_as}, depuis le {first_seen} | {same_as_score with a comma, e.g. 6,5/10, or « — » if null} | {« offre fantôme possible (vue depuis le {first_seen}) » if possible_ghost is true, else « — »} |

{If a list is empty: write « Aucune. » under its heading.}
```

---

## Example of a filled-in offer (form only)

```markdown
### 1. Stage Assistant comptable — Exemple SAS
**Note : 8,8/10**

Poste d'assistant comptable dans une équipe, avec des échanges réguliers avec les clients. Les tâches sont variées, de la saisie à la préparation des bilans. L'offre ne dit pas qui encadre le stage.

| | |
|---|---|
| Contrat | stage — 6 mois |
| Début | mars 2028 |
| Lieu | Lyon 3e (69003) |
| Mode de travail | hybride |
| Part de travail sur le terrain | ~20 % (estimation) |
| Publiée le | 2026-10-25 |
| Source | La bonne alternance |
| Lien | https://example.com/offres/EXEMPLE |

**Points forts**
- Poste prioritaire (assistant comptable)
- Beaucoup d'échanges avec les clients

**Points faibles**
- Encadrement non précisé

<details><summary>Détail de la note</summary>

| Critère | Points |
|---|---|
| Type de poste | 20 / 20 |
| Place de la comptabilité | 15 / 15 |
| Part de travail sur le terrain | 10 / 10 |
| Échanges avec les clients | 15 / 15 |
| Apprentissage | 3 / 15 (équipe +3) |
| Mode de travail | 5 / 5 |
| Dates et durée | 10 / 10 |
| Type de contrat | 10 / 10 |
| Plafond appliqué | aucun |
| **Total** | **88 / 100 → 8,8 / 10** |

</details>
```
