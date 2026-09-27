"""
MatterTrace data models.

Everything is kept in memory (Python dicts/lists) for prototype simplicity,
per Assignment 2's Timeline Store / Document Store design. A real deployment
would back this with a database, but the control logic (source links, labels,
human-only approval) is identical either way, which is what this prototype
demonstrates.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import hashlib
import itertools

_id_counter = itertools.count(1)


def next_id(prefix: str) -> str:
    return f"{prefix}-{next(_id_counter):04d}"


LABELS = ["Client said", "From a document", "Checked by a person", "Mismatch or unclear"]
ROLES = ["intake", "paralegal", "attorney", "administrator"]


@dataclass
class User:
    username: str
    role: str  # one of ROLES


@dataclass
class Case:
    case_id: str
    title: str
    assigned_users: list = field(default_factory=list)  # usernames allowed to see this case
    status: str = "open"


@dataclass
class Document:
    doc_id: str
    case_id: Optional[str]  # None until assigned -> "needs a case"
    filename: str
    text: str
    content_hash: str
    uploaded_at: str
    uploaded_by: str
    version: int = 1
    is_duplicate: bool = False
    readable: bool = True  # False simulates a bad scan / unreadable doc


@dataclass
class TimelineEntry:
    entry_id: str
    case_id: str
    date: Optional[str]
    description: str
    parties: str
    amount: Optional[str]
    label: str  # one of LABELS
    source_doc_id: Optional[str]
    source_passage: Optional[str]
    status: str  # "suggested" | "checked" | "escalated" | "approved" | "rejected"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    original_suggestion: Optional[dict] = None  # snapshot of the AI's original proposal
    needs_second_look: bool = False
    mismatch_with: Optional[str] = None  # entry_id of the conflicting entry, if any


@dataclass
class MissingRecord:
    record_id: str
    case_id: str
    description: str
    mentioned_in_doc: str


@dataclass
class ActivityLogEntry:
    log_id: str
    timestamp: str
    actor: str
    action: str
    target: str
    before: Optional[str]
    after: Optional[str]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]
