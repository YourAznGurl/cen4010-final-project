"""
AI Extraction Service (mocked).

Per Assignment 2's architecture, this component reads a document's text and
suggests timeline entries with a source link and a label. In this prototype
it is a deterministic, rule-based "AI" (regex + heuristics) instead of a real
LLM call, so the prototype is free to run, has no external dependency, and
its output is 100% reproducible for grading/testing -- which is what NFR-09
(accuracy) and NFR-11 (AI version recorded on every output) ask for.

If this were swapped for a real LLM (e.g. the Anthropic API), only this
module would change; the rest of the architecture (Timeline Store, Review
Workbench, escalation, approval) is unaffected. That swap point is called
out explicitly in the README and Solution Design Report as the documented
next step.
"""
import re
from datetime import datetime
from app.models import TimelineEntry, next_id, LABELS

EXTRACTOR_VERSION = "mock-extractor-v1.0"

DATE_PATTERN = re.compile(
    r"\b(\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b"
)
AMOUNT_PATTERN = re.compile(r"\$\s?[\d,]+(?:\.\d{2})?")
# Simple heuristic for "who/what organization" -- capitalized multi-word sequences
PARTY_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
# Words that are only capitalized because they start a sentence, not because
# they're a name -- without this filter the regex above produces meaningless
# "parties" like "On" or "The". Any match made up entirely of these words is
# dropped rather than shown to the reviewer.
PARTY_STOPWORDS = {
    "On", "The", "A", "An", "In", "At", "After", "Before", "During", "For",
    "With", "From", "By", "As", "Additional", "Total", "According", "Per",
}
# Common abbreviations whose period would otherwise be mistaken for a
# sentence boundary (e.g. "Dr. Lee" splitting into "Dr." + "Lee").
ABBREVIATIONS = ["Dr.", "Mr.", "Mrs.", "Ms.", "St.", "Jr.", "Sr.", "vs.", "No."]
UNREADABLE_MARKERS = ["[ILLEGIBLE]", "[UNREADABLE]", "%%%GARBLED%%%"]
COURT_DEADLINE_KEYWORDS = ["court", "deadline", "hearing", "filing", "statute of limitations", "motion"]
MISSING_RECORD_PATTERN = re.compile(
    r"(?:requested|pending|awaiting|not yet received|has not arrived|outstanding)\s+([^\.\n]{3,80})",
    re.IGNORECASE,
)


def is_readable(text: str) -> bool:
    return not any(marker in text for marker in UNREADABLE_MARKERS)


def split_sentences(text: str):
    # Naive sentence splitter; good enough for a mocked extractor over short
    # sample docs. Abbreviation periods (e.g. "Dr.") are temporarily masked
    # so they aren't mistaken for sentence-ending punctuation.
    protected = text
    for ab in ABBREVIATIONS:
        protected = protected.replace(ab, ab.replace(".", "\u2022"))
    parts = re.split(r"(?<=[.!?])\s+", protected.strip())
    parts = [p.replace("\u2022", ".") for p in parts]
    return [p.strip() for p in parts if p.strip()]


def extract_parties(sentence: str) -> str:
    """Returns a comma-separated string of plausible named parties/orgs in
    the sentence, or 'Unknown' if nothing meaningful survives filtering."""
    raw_matches = PARTY_PATTERN.findall(sentence)
    meaningful = [
        m for m in dict.fromkeys(raw_matches)
        if not all(word in PARTY_STOPWORDS for word in m.split())
    ]
    return ", ".join(meaningful) if meaningful else "Unknown"


def extract_entries(document) -> list:
    """
    Returns a list of TimelineEntry (status='suggested') proposed from one
    document's text. Every entry carries source_doc_id + source_passage
    (FR-04) and a label of "Client said" or "From a document" (FR-05 --
    the AI never sets "Checked by a person").
    """
    entries = []
    if not is_readable(document.text):
        # NFR-12: unreadable content is flagged for a person, nothing guessed.
        return entries

    sentences = split_sentences(document.text)
    for sentence in sentences:
        dates = DATE_PATTERN.findall(sentence)
        amounts = AMOUNT_PATTERN.findall(sentence)
        if not dates and not amounts:
            continue  # only sentences carrying a date or amount become candidate events

        parties_str = extract_parties(sentence)

        label = "Client said" if "client" in document.filename.lower() or "intake" in document.filename.lower() else "From a document"

        entry = TimelineEntry(
            entry_id=next_id("ENT"),
            case_id=document.case_id,
            date=dates[0] if dates else None,
            description=sentence.strip(),
            parties=parties_str,
            amount=amounts[0] if amounts else None,
            label=label,
            source_doc_id=document.doc_id,
            source_passage=sentence.strip(),
            status="suggested",
        )
        entry.original_suggestion = {
            "date": entry.date,
            "description": entry.description,
            "parties": entry.parties,
            "amount": entry.amount,
            "label": entry.label,
            "extractor_version": EXTRACTOR_VERSION,
        }
        entries.append(entry)
    return entries


def find_missing_records(document):
    """FR-07: list records mentioned but not on file, from language like
    'requested', 'pending', 'has not arrived'. Returns the full sentence
    for readability rather than just the regex capture group."""
    if not is_readable(document.text):
        return []
    found = []
    for sentence in split_sentences(document.text):
        if MISSING_RECORD_PATTERN.search(sentence):
            found.append(sentence.strip())
    return found


def is_risky(entry: TimelineEntry) -> bool:
    """FR-09: items that must be escalated to the attorney -- mismatches,
    court/deadline mentions, or anything unreadable/uncertain."""
    if entry.label == "Mismatch or unclear":
        return True
    text = (entry.description or "").lower()
    return any(keyword in text for keyword in COURT_DEADLINE_KEYWORDS)


def detect_mismatches(entries: list) -> list:
    """
    FR-06: when two entries in the same case describe the same date but
    disagree on amount or parties, flag both as 'Mismatch or unclear' and
    link them to each other. Simple same-date heuristic, sufficient for a
    bounded prototype and its planted sample-case test.
    """
    by_date = {}
    for e in entries:
        if e.date:
            by_date.setdefault(e.date, []).append(e)

    mismatched_pairs = []
    for date, group in by_date.items():
        if len(group) < 2:
            continue
        # Only compare entries that actually name a dollar amount for that date --
        # comparing free-text "parties" heuristically produced false positives
        # (e.g. flagging a sentence with no amount just for having different
        # capitalized words), so amount disagreement is the sole trigger here.
        with_amounts = [e for e in group if e.amount]
        for i in range(len(with_amounts)):
            for j in range(i + 1, len(with_amounts)):
                a, b = with_amounts[i], with_amounts[j]
                if a.amount != b.amount:
                    mismatched_pairs.append((a, b))

    for a, b in mismatched_pairs:
        a.label = "Mismatch or unclear"
        b.label = "Mismatch or unclear"
        a.mismatch_with = b.entry_id
        b.mismatch_with = a.entry_id

    return mismatched_pairs
