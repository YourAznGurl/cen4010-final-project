# MatterTrace

AI-assisted case timelines for a personal-injury law office. This is the
Final Project prototype for CEN 4010,
continuing the project defined in Assignment 1 and designed in Assignment 2.

**Repository:** (https://github.com/YourAznGurl/cen4010-final-project)

## 1. Problem, in one paragraph

Personal-injury case information (client accounts, medical records, insurance
letters, court papers) arrives from many sources over months or years. Staff
rebuild case timelines by hand, and it's easy to lose track of where a fact
came from, whether anyone has checked it, or whether two sources disagree.
MatterTrace reads documents for one case, suggests timeline entries with a
source link and a reliability label, flags mismatches and missing records,
and requires a paralegal to check every suggestion and an attorney to give
final approval. The AI only ever suggests — it never approves anything
itself. Full problem scenario and requirements are in the Solution Design
Report (Assignments 1–2, carried into this repo).

## 2. What this prototype demonstrates (bounded scope)

Per the Final Project brief, this is a **focused, bounded slice** — not the
full platform — chosen to demonstrate the entire suggest → review → escalate
→ approve loop end-to-end, since that loop (not any single feature) is
MatterTrace's core value proposition.

**Implemented (demonstrated and tested):**
- FR-01 — a document is never processed without exactly one case; duplicates are flagged and skipped
- FR-02 — every document tracks source, upload time, uploader, version
- FR-03/FR-04 — AI Extraction Service suggests timeline entries, each linked to its source document and exact source sentence
- FR-05 — every entry carries exactly one label; the AI never sets "Checked by a person" — only a signed-in reviewer can
- FR-06 — same-date entries with conflicting dollar amounts are flagged "Mismatch or unclear," both sources kept, no winner picked
- FR-07 — language like "requested," "pending," "has not arrived" is listed as a missing record; no entry is invented for it
- FR-08 — paralegal approve/fix/reject/mark-unclear actions are all logged with actor, timestamp, and before/after values
- FR-09 — mismatches, court/deadline mentions, and anything a paralegal marks unclear are escalated to an attorney-only queue; only the attorney role can give final approval
- FR-10 — exported timeline is labeled "Draft - not approved by attorney" until approval, and includes a label key
- FR-12 — legal-advice / valuation / negotiation questions are refused and redirected to an attorney
- NFR-02 — role-based access (intake, paralegal, attorney, administrator); blocked actions are logged
- NFR-08 — no entry becomes "Checked" or the timeline "Approved" without a recorded human action
- NFR-10 — full activity log (upload, suggestion, review, escalation, approval) with before/after
- NFR-12 — unreadable documents are flagged for a person; nothing is guessed

**Explicitly out of scope for this prototype** (see Limitations, section 7):
- FR-11 (re-flagging earlier entries when a new document contradicts them)
- Real authentication (login is a role-picker, not a password system)
- A real LLM call (the AI Extraction Service is a deterministic, rule-based mock — see section 4)
- A persistent database (all data is in-memory and resets when the app restarts)

## 3. Architecture summary

Follows the **Document Intelligence** canonical architecture chosen in
Assignment 2: documents come in, an extraction step proposes structured
suggestions with source links, suggestions are held separately from
human-checked entries, a review step lets a person check them, risky items
escalate to a decision-maker, and an output step builds the final work
product (here, the case timeline).

```
Document Intake → Document Store → AI Extraction Service → Timeline Store
                                                                  |
                                                    Review Workbench (paralegal)
                                                                  |
                                              Attorney Queue (risky items only)
                                                                  |
                                                    Report/Export (Draft/Approved)
```

Code layout:
```
app/
  models.py       Case, Document, TimelineEntry, MissingRecord, ActivityLogEntry
  extraction.py   Mocked AI Extraction Service (regex-based, deterministic, free)
  store.py        In-memory Timeline Store + all control-point logic (C1-C6)
  seed_demo.py    Loads one demo case with planted test conditions on startup
  main.py         Flask routes (Document Intake, Review Workbench, Attorney Queue, Export)
  templates/      Server-rendered HTML pages
tests/
  test_mattertrace.py   pytest suite, one test per FR/NFR control point
```

## 4. Prerequisites

- Python 3.10+
- pip (internet access, to install Flask and pytest)

No API keys, no external services, no cost. The AI Extraction Service is a
deterministic rule-based module (see `app/extraction.py`), not a live LLM
call — documented as a design choice in section 4 there, with the swap point
called out for anyone extending this into a real LLM-backed version later.

## 5. Setup and run

```bash
# from the project root (the folder containing this README)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python -m app.main
```

Open **http://127.0.0.1:5000** in a browser. A demo case ("Doe v. Acme
Trucking Co.") is seeded automatically on startup with the planted
conditions described in section 6.

**Logging in:** there's no password — pick a seeded user from the dropdown
to demonstrate each role:
| Username | Role |
|---|---|
| dana_intake | intake |
| pat_paralegal | paralegal |
| alex_attorney | attorney |
| sam_admin | administrator |

## 6. Demonstration path (normal and exception cases)

The seeded demo case includes every planted condition called for in
Assignment 2's Implementation Guidelines:

1. **Log in as `dana_intake`.** Visit "Needs a Case" — see `stray_fax.txt`
   waiting because it has no case assigned (FR-01).
2. **Log in as `pat_paralegal`, open the case.** You'll see:
   - A duplicate document flagged and skipped (`medical_record_1_dup.txt`)
   - Two unreadable documents flagged (`scan_bad1.txt`, `scan_bad2.txt`)
   - Suggested entries with source links, awaiting review
   - A missing-records list (police report, medical records, wage-loss docs)
3. **Approve a normal suggestion** (e.g. the client's $1,200 statement) — it
   becomes "Checked by a person," reviewer and timestamp recorded.
4. **Approve one of the three mismatched entries** (same date, different
   dollar amounts from medical/insurance/police sources) — instead of
   approving, it's automatically escalated to the attorney queue.
5. **Approve the court/hearing-deadline entry** — same automatic escalation.
6. **Log in as `alex_attorney`.** Open "Attorney Queue" — see all escalated
   items with both conflicting sources shown side by side. Resolve them.
7. **Try to approve the timeline before resolving the queue** — blocked with
   a message naming how many items remain.
8. **Once the queue is clear, approve the timeline.** Export it — status
   flips from "Draft - not approved by attorney" to "Approved by attorney."
9. **Log in as `pat_paralegal` and try to open the Attorney Queue directly,
   or approve the timeline** — both are blocked (NFR-02).
10. **Visit "Ask MatterTrace"** and ask "What is this case worth?" — refused
    and redirected to an attorney (FR-12). Ask a timeline-scoped question
    instead — answered.
11. **Visit "Activity Log"** — every action above appears with actor,
    timestamp, and before/after values (NFR-10).

## 7. Testing

```bash
pip install pytest   # if not already installed via requirements.txt
pytest tests/ -v
```

The suite (`tests/test_mattertrace.py`) has one or more tests per FR/NFR
listed in section 2, run directly against the store's control logic
(independent of the Flask HTTP layer, so failures point straight to the
business rule that broke). All 30 tests were passing at time of submission.

## 8. Known limitations

- **Mocked AI, not a real LLM.** `app/extraction.py` uses regex/heuristics
  instead of calling an actual language model. This keeps the prototype
  free, fast, and 100% reproducible for grading, but it means extraction
  quality is much cruder than what a real LLM would produce (e.g., it can
  only find dates it recognizes by pattern, and sentence-splitting on
  abbreviations like "Dr." occasionally produces an oddly-cut sentence in
  the missing-records list). Swapping in a real LLM call would only require
  changing `extraction.py` — the rest of the architecture is unaffected.
- **Mismatch detection is same-date + conflicting-amount only.** Assignment
  2's design describes a broader notion of mismatch (dates, people, amounts,
  descriptions). This prototype implements the amount-based case fully and
  documents the rest as a next step, per the Final Project's "bounded slice"
  guidance rather than an unfinished broad platform.
- **FR-11 (re-flagging earlier entries on a contradicting new document) is
  not implemented** in this slice — the Timeline Store's data model supports
  it (`needs_second_look` field exists on every entry) but the triggering
  logic was left out to keep the prototype focused, per the advisory to
  prefer "a small capability with clear evidence" over a broader unfinished
  one.
- **No real authentication or database.** Login is a role-picker for
  demonstrating access control, not a production auth system. All data is
  in-memory and resets on restart — intentional for a free, dependency-free
  prototype; a real deployment would add a database and real auth without
  changing the control logic in `store.py`.
- **No interview-based validation of the problem statement.** As noted in
  Assignment 2's Proof of Demand section, this project is grounded in the
  instructor-provided Injury Law Office scenario rather than a live
  stakeholder interview.

## 9. AI-assisted development record

Claude (Anthropic) was used to design and implement this prototype's code,
tests, and documentation, continuing the AI-assisted process disclosed in
Assignments 1 and 2. Specifically:
- Claude proposed the module structure (`models.py`, `extraction.py`,
  `store.py`, `main.py`), the mocked rule-based extraction approach, and the
  Flask routes/templates, based on the architecture and requirements from
  Assignment 2.
- Claude wrote the initial extraction logic, then two defects were found
  through direct testing and corrected: (1) a false-positive mismatch caused
  by comparing free-text "parties" heuristically, removed in favor of
  amount-only comparison; (2) missing-record descriptions were truncated by
  the original regex capture group, fixed to report the full sentence.
- Every control point (FR-01 through FR-12, relevant NFRs) was verified two
  ways: automated pytest tests against the store logic, and manual end-to-end
  HTTP testing (login → upload → review → escalate → attorney-resolve →
  approve → export) to confirm the Flask layer enforces the same rules.
- I reviewed the generated code and test results, ran the application
  myself, and directed which requirements to prioritize in this bounded
  slice versus defer as documented limitations (section 8).

## 10. Next steps

- Replace the mocked extraction with a real LLM call (e.g., the Anthropic
  API), constrained to only propose entries, cite sources, and flag
  mismatches/missing records — never to approve anything (NFR-11).
- Implement FR-11 (re-flagging affected entries when a new document
  contradicts an approved one) using the existing `needs_second_look` field.
- Add a real database and authentication before handling any real client
  data, and formally document the AI service's data-handling terms (NFR-03)
  before that point.
