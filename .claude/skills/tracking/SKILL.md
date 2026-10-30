---
name: tracking
description: Record or look up my tracking (applications, follow-ups, interviews, answers, rejections, offers I found myself, notes). Use when the request starts with "Tracking", when I tell you what I did on my side, or when I ask where I stand with a company.
---

# My tracking

You keep my tracking in the `memory` MCP server. I talk to you simply, in French ("j'ai postulé chez Nova hier"): you put it in the right format.
**Nothing is ever deleted**: no row is erased or modified.
**Talk to me in French** (simple French), and write the `text` field in French.

## Record something

### 1. Understand
For each action in my message, find:

| Field | How |
|---|---|
| `type` | See the table below |
| `company` | The name I give |
| `date` | Format YYYY-MM-DD. Compute "hier" (yesterday), "lundi" (Monday)… from today's date given in the request. If I say nothing: leave it empty (= today) |
| `text` | A short sentence in French, with **my** information (channel, contact, next step…). Add nothing I did not say |

| What I say | `type` |
|---|---|
| postulé, candidaté, envoyé mon CV (applied, sent my CV) | `application` |
| relancé (followed up) | `follow_up` |
| entretien, call, visio, test (planned or done) | `interview` |
| positive or neutral answer, request for information | `answer` |
| refus, « pas retenu » (rejected) | `rejection` |
| je laisse tomber, plus intéressé(e) (I give up, no longer interested) | `dropped` |
| anything else | `note` |

### 2. Find the offer
Call `find` with the company name (or a word of the title).
- **A single offer** matches → use its `id` as `offer_id`.
- **Several** → show them to me (id, title, date) and ask which one.
- **None** → ask me: either you create the offer with `add_offer` (you need at least the title and the company; `source` = where I found it, e.g. `site_entreprise`), or you record the action without an offer (only the company).

### 3. Ask for my agreement
Before writing, show a summary (column names in French) and ask **« Je l'enregistre ? »**:

| Date | Type | Entreprise | Offre | Texte |
|---|---|---|---|---|
| 2026-10-26 | application | Nova | la_bonne_alternance:0123abc | Postulé via le site, contact : Mme Martin |

Several actions in one message → one single table, one single question.
**Call `add_tracking` or `add_offer` only after my "oui".** If I correct something, redo the table.
If you asked me a multiple-choice question (e.g. A or B) and my answer does not choose, **do not choose for me**: ask again, and write nothing.

### 4. Save
Call the tools, then confirm in one line with the number of each row (`num`).
If a tool returns an error, tell me what it says and suggest a fix.

## Fix a mistake
Nothing is erased. Add a row of type `note`: « Correction de la ligne n°X : … ». Ask for my agreement as usual.

## Look up
- "Où j'en suis ?", "mes dernières actions" → `history`.
- "Où j'en suis avec Nova ?" → `find`.

Answer briefly, with a table. Change nothing in the database while looking up.

## Forbidden in this skill
- Any action listed in "You must NEVER" in `CLAUDE.md` (no application, no message, no cover letter…).
- Writing to the database without my agreement (step 3).
- Inventing a date, a contact, a URL or any information.
- Calling `filter_already_seen` or `save_evaluations`: they are only for the offer search.
