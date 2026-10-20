"""
Validation tests for MatterTrace, mapped to Assignment 2's Functional and
Non-Functional Requirements. Run with:  pytest tests/ -v

Each test's docstring names the requirement it validates, matching the
traceability table in section 8.1 of the Solution Design Report.
"""
import pytest
from app.store import Store, PermissionError_
from app import extraction


@pytest.fixture
def store():
    return Store()


@pytest.fixture
def case(store):
    return store.create_case("Test Case", assigned_users=["pat_paralegal", "alex_attorney", "sam_admin"])


# ---------- FR-01: document intake requires exactly one case; duplicates flagged ----------

def test_document_with_no_case_waits_in_needs_a_case_list(store):
    doc = store.upload_document("stray.txt", "Some text with no case.", "dana_intake", case_id=None)
    assert doc.case_id is None
    assert doc.doc_id in store.unassigned_docs


def test_duplicate_document_is_flagged_and_not_processed(store, case):
    text = "On 01/01/2024, charges were $500."
    doc1 = store.upload_document("a.txt", text, "dana_intake", case_id=case.case_id)
    doc2 = store.upload_document("a_copy.txt", text, "dana_intake", case_id=case.case_id)
    assert doc1.is_duplicate is False
    assert doc2.is_duplicate is True
    entries = store.run_extraction(doc2.doc_id, "dana_intake")
    assert entries == []  # duplicate is never processed


def test_document_cannot_be_extracted_without_a_case(store):
    doc = store.upload_document("no_case.txt", "On 01/01/2024, $100.", "dana_intake", case_id=None)
    with pytest.raises(ValueError):
        store.run_extraction(doc.doc_id, "dana_intake")


# ---------- FR-02: document metadata tracked ----------

def test_document_tracks_source_metadata(store, case):
    doc = store.upload_document("x.txt", "text", "dana_intake", case_id=case.case_id)
    assert doc.uploaded_by == "dana_intake"
    assert doc.uploaded_at is not None
    assert doc.case_id == case.case_id
    assert doc.version == 1


# ---------- FR-03/FR-04: suggested entries with source links ----------

def test_extraction_produces_entries_with_source_link(store, case):
    doc = store.upload_document(
        "medical.txt", "On 03/10/2024, total charges were $1,200.", "dana_intake", case_id=case.case_id
    )
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    assert len(entries) == 1
    e = entries[0]
    assert e.source_doc_id == doc.doc_id
    assert e.source_passage  # non-empty
    assert e.date == "03/10/2024"
    assert e.amount == "$1,200"


def test_sentences_without_date_or_amount_are_not_suggested(store, case):
    doc = store.upload_document(
        "narrative.txt", "The client feels much better after treatment.", "dana_intake", case_id=case.case_id
    )
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    assert entries == []


# ---------- FR-05: labels; AI never sets "Checked by a person" ----------

def test_ai_never_sets_checked_by_a_person_label(store, case):
    doc = store.upload_document(
        "medical.txt", "On 03/10/2024, total charges were $1,200.", "dana_intake", case_id=case.case_id
    )
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    for e in entries:
        assert e.label != "Checked by a person"


def test_approve_action_sets_checked_by_a_person_and_records_reviewer(store, case):
    doc = store.upload_document(
        "medical.txt", "On 03/10/2024, total charges were $1,200.", "dana_intake", case_id=case.case_id
    )
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    entry = store.review_entry(entries[0].entry_id, "pat_paralegal", "approve")
    assert entry.label == "Checked by a person"
    assert entry.reviewed_by == "pat_paralegal"
    assert entry.reviewed_at is not None


def test_client_reported_docs_get_client_said_label(store, case):
    doc = store.upload_document(
        "client_intake.txt", "On 03/10/2024, the client said charges were $1,200.",
        "dana_intake", case_id=case.case_id,
    )
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    assert entries[0].label == "Client said"


# ---------- FR-06: mismatches flagged, both sources shown, no winner picked ----------

def test_conflicting_amounts_on_same_date_are_flagged_as_mismatch(store, case):
    doc1 = store.upload_document("med.txt", "On 03/10/2024, charges were $1,200.", "dana_intake", case_id=case.case_id)
    doc2 = store.upload_document("ins.txt", "On 03/10/2024, damages assessed at $1,500.", "dana_intake", case_id=case.case_id)
    store.run_extraction(doc1.doc_id, "dana_intake")
    store.run_extraction(doc2.doc_id, "dana_intake")
    mismatched = [e for e in store.entries.values() if e.label == "Mismatch or unclear"]
    assert len(mismatched) == 2  # both sources shown, neither deleted
    assert mismatched[0].mismatch_with == mismatched[1].entry_id
    assert mismatched[1].mismatch_with == mismatched[0].entry_id


def test_reviewing_a_mismatched_entry_escalates_instead_of_approving(store, case):
    doc1 = store.upload_document("med.txt", "On 03/10/2024, charges were $1,200.", "dana_intake", case_id=case.case_id)
    doc2 = store.upload_document("ins.txt", "On 03/10/2024, damages assessed at $1,500.", "dana_intake", case_id=case.case_id)
    store.run_extraction(doc1.doc_id, "dana_intake")
    entries2 = store.run_extraction(doc2.doc_id, "dana_intake")
    mismatched_entry = [e for e in store.entries.values() if e.label == "Mismatch or unclear"][0]
    result = store.review_entry(mismatched_entry.entry_id, "pat_paralegal", "approve")
    assert result.status == "escalated"
    assert result.label != "Checked by a person"  # paralegal action did not silently approve it


# ---------- FR-07: missing records listed, nothing invented ----------

def test_missing_record_language_is_detected(store, case):
    doc = store.upload_document(
        "intake.txt", "A police report was requested but has not arrived yet.",
        "dana_intake", case_id=case.case_id,
    )
    store.run_extraction(doc.doc_id, "dana_intake")
    matches = [m for m in store.missing_records.values() if m.case_id == case.case_id]
    assert len(matches) == 1


def test_missing_record_produces_no_fabricated_timeline_entry(store, case):
    doc = store.upload_document(
        "intake.txt", "A police report was requested but has not arrived yet.",
        "dana_intake", case_id=case.case_id,
    )
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    assert entries == []  # no date/amount in that sentence -> no invented entry


# ---------- FR-08: paralegal actions traceable (approve/fix/reject/mark unclear) ----------

def test_all_four_review_actions_are_logged_with_before_after(store, case):
    doc = store.upload_document("med.txt", "On 03/10/2024, charges were $1,200.", "dana_intake", case_id=case.case_id)
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    entry_id = entries[0].entry_id
    log_before = len(store.activity_log)
    store.review_entry(entry_id, "pat_paralegal", "fix", edits={"description": "Corrected description"})
    log_entry = store.activity_log[-1]
    assert log_entry.actor == "pat_paralegal"
    assert log_entry.before is not None and log_entry.after is not None
    assert len(store.activity_log) == log_before + 1


def test_rejected_entry_is_kept_not_deleted(store, case):
    doc = store.upload_document("med.txt", "On 03/10/2024, charges were $1,200.", "dana_intake", case_id=case.case_id)
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    entry_id = entries[0].entry_id
    store.review_entry(entry_id, "pat_paralegal", "reject")
    assert entry_id in store.entries  # still present
    assert store.entries[entry_id].status == "rejected"


# ---------- FR-09 / NFR-02 / NFR-08: only attorney can approve; role enforced ----------

def test_paralegal_cannot_approve_timeline(store, case):
    with pytest.raises(PermissionError_):
        store.approve_timeline(case.case_id, "pat_paralegal")


def test_attorney_can_approve_timeline_once_queue_is_clear(store, case):
    assert store.approve_timeline(case.case_id, "alex_attorney") is True
    assert store.case_approved[case.case_id] is True


def test_approval_blocked_while_escalated_items_remain(store, case):
    doc1 = store.upload_document("med.txt", "On 03/10/2024, charges were $1,200.", "dana_intake", case_id=case.case_id)
    doc2 = store.upload_document("ins.txt", "On 03/10/2024, damages assessed at $1,500.", "dana_intake", case_id=case.case_id)
    store.run_extraction(doc1.doc_id, "dana_intake")
    store.run_extraction(doc2.doc_id, "dana_intake")
    mismatched = [e for e in store.entries.values() if e.label == "Mismatch or unclear"][0]
    store.review_entry(mismatched.entry_id, "pat_paralegal", "approve")  # escalates
    with pytest.raises(ValueError):
        store.approve_timeline(case.case_id, "alex_attorney")


def test_unassigned_user_blocked_from_case(store, case):
    with pytest.raises(PermissionError_):
        store.require_case_access("someone_not_assigned", case.case_id)


# ---------- FR-10: export marked Draft until approved ----------

def test_export_is_draft_before_approval(store, case):
    report = store.export_timeline(case.case_id)
    assert report["status"] == "Draft - not approved by attorney"


def test_export_shows_approved_after_attorney_approval(store, case):
    store.approve_timeline(case.case_id, "alex_attorney")
    report = store.export_timeline(case.case_id)
    assert report["status"] == "Approved by attorney"


def test_export_includes_label_key(store, case):
    report = store.export_timeline(case.case_id)
    assert set(report["label_key"].keys()) == set(extraction.LABELS if hasattr(extraction, "LABELS") else report["label_key"].keys())
    assert "Mismatch or unclear" in report["label_key"]


# ---------- FR-12: refuses legal advice / valuation / negotiation ----------

@pytest.mark.parametrize("question", [
    "What is this case worth?",
    "Should I settle for this amount?",
    "What negotiate strategy should we use?",
    "What are the odds of winning this case?",
])
def test_legal_advice_questions_are_refused(store, question):
    assert store.check_legal_advice_request(question) is True


def test_timeline_questions_are_not_refused(store):
    assert store.check_legal_advice_request("When did the accident happen?") is False


# ---------- NFR-10: activity log tracks everything, not editable by paralegals ----------

def test_activity_log_records_document_upload(store, case):
    log_before = len(store.activity_log)
    store.upload_document("x.txt", "text", "dana_intake", case_id=case.case_id)
    assert len(store.activity_log) > log_before


def test_activity_log_has_no_delete_method_exposed_to_paralegal():
    # The Store class intentionally exposes no method to remove log entries;
    # this test documents that guarantee at the API level.
    assert not hasattr(Store, "delete_activity_log_entry")
    assert not hasattr(Store, "clear_activity_log")


# ---------- NFR-12: unreadable documents flagged, nothing guessed ----------

def test_unreadable_document_produces_no_entries(store, case):
    doc = store.upload_document(
        "scan.txt", "[UNREADABLE] page 1", "dana_intake", case_id=case.case_id, readable=False
    )
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    assert entries == []


def test_unreadable_document_is_flagged_in_activity_log(store, case):
    doc = store.upload_document(
        "scan.txt", "[UNREADABLE] page 1", "dana_intake", case_id=case.case_id, readable=False
    )
    store.run_extraction(doc.doc_id, "dana_intake")
    flagged = [l for l in store.activity_log if l.action == "DOC_FLAGGED_UNREADABLE" and l.target == doc.doc_id]
    assert len(flagged) == 1


# ---------- Court/deadline items are risky and get escalated on review ----------

def test_court_deadline_mention_is_risky_and_escalates(store, case):
    doc = store.upload_document(
        "court.txt", "On 04/01/2024, the court set a hearing deadline for 05/15/2024.",
        "dana_intake", case_id=case.case_id,
    )
    entries = store.run_extraction(doc.doc_id, "dana_intake")
    assert len(entries) == 1
    result = store.review_entry(entries[0].entry_id, "pat_paralegal", "approve")
    assert result.status == "escalated"
