"""
In-memory store + control logic for MatterTrace.

This module is where the Assignment 2 control points (C1-C6) and the
Must/Should requirements actually get enforced:
  C1 / FR-01: a document needs exactly one case before it's used.
  C2 / FR-04: every suggested entry carries a source link.
  C3 / FR-05: only a signed-in reviewer can set "Checked by a person".
  C4 / FR-09: risky items are routed to the attorney queue.
  C5 / FR-09: only the attorney role can approve a case's timeline.
  C6 / FR-10: exports are marked Draft until approved.
"""
from app.models import (
    Case, Document, TimelineEntry, MissingRecord, ActivityLogEntry,
    User, next_id, now, hash_text, ROLES,
)
from app import extraction


class PermissionError_(Exception):
    pass


class Store:
    def __init__(self):
        self.users = {}          # username -> User
        self.cases = {}          # case_id -> Case
        self.documents = {}      # doc_id -> Document
        self.entries = {}        # entry_id -> TimelineEntry
        self.missing_records = {}  # record_id -> MissingRecord
        self.activity_log = []   # list[ActivityLogEntry]
        self.unassigned_docs = []  # doc_ids with no case yet ("needs a case" list)
        self.case_approved = {}  # case_id -> bool (attorney approval, FR-10/C5)
        self._seed_users()

    # ---------- setup ----------
    def _seed_users(self):
        for username, role in [
            ("dana_intake", "intake"),
            ("pat_paralegal", "paralegal"),
            ("alex_attorney", "attorney"),
            ("sam_admin", "administrator"),
        ]:
            self.users[username] = User(username=username, role=role)

    def log(self, actor, action, target, before=None, after=None):
        entry = ActivityLogEntry(
            log_id=next_id("LOG"), timestamp=now(), actor=actor,
            action=action, target=target, before=before, after=after,
        )
        self.activity_log.append(entry)
        return entry

    # ---------- roles / access (NFR-01, NFR-02) ----------
    def require_role(self, username, allowed_roles):
        user = self.users.get(username)
        if not user or user.role not in allowed_roles:
            self.log(username or "unknown", "BLOCKED_ROLE", target=str(allowed_roles))
            raise PermissionError_(f"Role check failed for '{username}': requires {allowed_roles}")
        return user

    def require_case_access(self, username, case_id):
        case = self.cases.get(case_id)
        user = self.users.get(username)
        if not case or not user:
            raise PermissionError_("Unknown case or user")
        if user.role == "administrator":
            return case
        if username not in case.assigned_users:
            self.log(username, "BLOCKED_CASE_ACCESS", target=case_id)
            raise PermissionError_(f"'{username}' is not assigned to case {case_id}")
        return case

    # ---------- cases ----------
    def create_case(self, title, assigned_users):
        case = Case(case_id=next_id("CASE"), title=title, assigned_users=assigned_users)
        self.cases[case.case_id] = case
        self.case_approved[case.case_id] = False
        self.log("system", "CASE_CREATED", target=case.case_id, after=title)
        return case

    # ---------- document intake (FR-01, FR-02 / C1) ----------
    def upload_document(self, filename, text, uploaded_by, case_id=None, readable=True):
        content_hash = hash_text(text)
        is_dup = any(
            d.content_hash == content_hash and d.case_id == case_id
            for d in self.documents.values()
        ) if case_id else any(d.content_hash == content_hash for d in self.documents.values())

        doc = Document(
            doc_id=next_id("DOC"), case_id=case_id, filename=filename, text=text,
            content_hash=content_hash, uploaded_at=now(), uploaded_by=uploaded_by,
            is_duplicate=is_dup, readable=readable,
        )
        self.documents[doc.doc_id] = doc

        if case_id is None:
            self.unassigned_docs.append(doc.doc_id)
            self.log(uploaded_by, "DOC_NEEDS_CASE", target=doc.doc_id)
        else:
            self.log(uploaded_by, "DOC_UPLOADED", target=doc.doc_id, after=case_id)

        if is_dup:
            self.log(uploaded_by, "DOC_FLAGGED_DUPLICATE", target=doc.doc_id)

        return doc

    def assign_case_to_doc(self, doc_id, case_id, actor):
        doc = self.documents[doc_id]
        before = doc.case_id
        doc.case_id = case_id
        if doc_id in self.unassigned_docs:
            self.unassigned_docs.remove(doc_id)
        self.log(actor, "DOC_CASE_ASSIGNED", target=doc_id, before=before, after=case_id)
        return doc

    # ---------- AI extraction (FR-03 to FR-07) ----------
    def run_extraction(self, doc_id, actor):
        doc = self.documents[doc_id]
        if doc.case_id is None:
            raise ValueError("Document has no case assigned; cannot process (C1).")
        if doc.is_duplicate:
            self.log(actor, "EXTRACTION_SKIPPED_DUPLICATE", target=doc_id)
            return []
        if not doc.readable:
            self.log(actor, "DOC_FLAGGED_UNREADABLE", target=doc_id)
            return []

        new_entries = extraction.extract_entries(doc)
        for e in new_entries:
            self.entries[e.entry_id] = e
        self.log(actor, "EXTRACTION_RUN", target=doc_id, after=f"{len(new_entries)} suggested entries")

        for desc in extraction.find_missing_records(doc):
            rec = MissingRecord(record_id=next_id("MISS"), case_id=doc.case_id,
                                 description=desc, mentioned_in_doc=doc_id)
            self.missing_records[rec.record_id] = rec

        # Re-check mismatches across the whole case each time new entries arrive.
        case_entries = [e for e in self.entries.values() if e.case_id == doc.case_id]
        extraction.detect_mismatches(case_entries)
        return new_entries

    # ---------- Review Workbench (FR-08, FR-09) ----------
    def review_entry(self, entry_id, actor, action, edits=None):
        """action: 'approve' | 'fix' | 'reject' | 'mark_unclear'"""
        self.require_role(actor, ["paralegal", "attorney", "administrator"])
        entry = self.entries[entry_id]
        self.require_case_access(actor, entry.case_id)
        before = f"{entry.label} | {entry.description}"

        if extraction.is_risky(entry):
            entry.status = "escalated"
            self.log(actor, "ENTRY_ESCALATED_ON_REVIEW", target=entry_id, before=before)
            return entry

        if action == "approve":
            entry.label = "Checked by a person"
            entry.status = "checked"
        elif action == "fix":
            if edits:
                entry.description = edits.get("description", entry.description)
                entry.date = edits.get("date", entry.date)
                entry.parties = edits.get("parties", entry.parties)
                entry.amount = edits.get("amount", entry.amount)
            entry.label = "Checked by a person"
            entry.status = "checked"
        elif action == "reject":
            entry.status = "rejected"  # kept in log, not deleted (per 7.3 error handling)
        elif action == "mark_unclear":
            entry.label = "Mismatch or unclear"
            entry.status = "escalated"
        else:
            raise ValueError(f"Unknown action: {action}")

        entry.reviewed_by = actor
        entry.reviewed_at = now()
        after = f"{entry.label} | {entry.description}"
        self.log(actor, f"ENTRY_{action.upper()}", target=entry_id, before=before, after=after)
        return entry

    # ---------- Attorney escalation & approval (FR-09, FR-12 / C4, C5) ----------
    def attorney_queue(self, case_id):
        return [e for e in self.entries.values() if e.case_id == case_id and e.status == "escalated"]

    def attorney_resolve(self, entry_id, actor, decision, edits=None):
        self.require_role(actor, ["attorney", "administrator"])
        entry = self.entries[entry_id]
        before = f"{entry.label} | {entry.status}"
        if decision == "approve":
            if edits:
                entry.description = edits.get("description", entry.description)
            entry.label = "Checked by a person"
            entry.status = "checked"
        elif decision == "reject":
            entry.status = "rejected"
        entry.reviewed_by = actor
        entry.reviewed_at = now()
        self.log(actor, "ATTORNEY_RESOLVED", target=entry_id, before=before,
                  after=f"{entry.label} | {entry.status}")
        return entry

    def approve_timeline(self, case_id, actor):
        """FR-09/C5: only an attorney (or admin) may approve. Refuses if
        escalated items remain unresolved."""
        self.require_role(actor, ["attorney", "administrator"])
        self.require_case_access(actor, case_id)
        pending = self.attorney_queue(case_id)
        if pending:
            raise ValueError(f"{len(pending)} escalated item(s) must be resolved before approval.")
        self.case_approved[case_id] = True
        self.log(actor, "TIMELINE_APPROVED", target=case_id)
        return True

    # ---------- Legal-advice refusal (FR-12) ----------
    LEGAL_ADVICE_KEYWORDS = [
        "what is this case worth", "case worth", "should i settle", "settlement amount",
        "negotiate", "legal advice", "legal strategy", "what should i offer",
        "should we take this case", "odds of winning", "how much can i sue",
    ]

    def check_legal_advice_request(self, question: str) -> bool:
        """Returns True if the question should be refused."""
        q = question.lower()
        return any(kw in q for kw in self.LEGAL_ADVICE_KEYWORDS)

    # ---------- Report / export (FR-10) ----------
    def export_timeline(self, case_id):
        entries = sorted(
            [e for e in self.entries.values() if e.case_id == case_id and e.status != "rejected"],
            key=lambda e: (e.date or "9999"),
        )
        approved = self.case_approved.get(case_id, False)
        return {
            "case_id": case_id,
            "status": "Approved by attorney" if approved else "Draft - not approved by attorney",
            "entries": entries,
            "missing_records": [m for m in self.missing_records.values() if m.case_id == case_id],
            "label_key": {
                "Client said": "Reported directly by the client, not yet verified.",
                "From a document": "Extracted from a document, not yet verified.",
                "Checked by a person": "Reviewed and confirmed by a paralegal or attorney.",
                "Mismatch or unclear": "Sources disagree, or the AI could not process this reliably.",
            },
        }


store = Store()
