"""
Seeds one demo case with the planted conditions called for in Assignment 2's
Implementation Guidelines section 8: a no-case document, a duplicate, planted
mismatches, planted missing-record mentions, and unreadable documents.

This is loaded automatically when the Flask app starts (see main.py) so a
grader/reviewer sees a populated, demonstrable case immediately rather than
having to hand-type documents first. Manual upload still works via the UI
for anyone who wants to test additional inputs.

Note (documented limitation): Assignment 2 asked for 5 planted mismatches and
2 unreadable documents in the full test case. This bounded prototype plants
3 mismatched entries (covering the same mismatch mechanism -- same-date,
different-amount/parties) and 2 unreadable documents, which is enough to
demonstrate and test the control (FR-06, NFR-12) without inflating the demo
data. See README "Known Limitations".
"""

DOCS = [
    {
        "filename": "client_intake.txt",
        "text": (
            "On 03/10/2024, the client was injured in a car accident on Main Street. "
            "The client said medical bills so far are $1,200. "
            "The client also mentioned that a police report was requested but has not arrived yet."
        ),
        "has_case": True,
    },
    {
        "filename": "medical_record_1.txt",
        "text": "On 03/10/2024, total medical charges were $1,200.",
        "has_case": True,
    },
    {
        "filename": "insurance_letter.txt",
        "text": (
            "On 03/10/2024, State Farm assessed damages at $1,500. "
            "Medical records requested from Dr. Lee have not arrived."
        ),
        "has_case": True,
    },
    {
        "filename": "police_report.txt",
        "text": "On 03/10/2024, the report lists total damages of $1,750.",
        "has_case": True,
    },
    {
        "filename": "court_notice.txt",
        "text": "On 04/01/2024, the court set a hearing deadline for 05/15/2024.",
        "has_case": True,
    },
    {
        "filename": "adjuster_notes.txt",
        "text": "Additional wage-loss documentation is still pending from the employer.",
        "has_case": True,
    },
    {
        "filename": "medical_record_1_dup.txt",
        "text": "On 03/10/2024, total medical charges were $1,200.",  # identical text -> duplicate
        "has_case": True,
    },
    {
        "filename": "stray_fax.txt",
        "text": "On 06/01/2024, a fax arrived that has not been matched to any case yet.",
        "has_case": False,  # planted "needs a case" document
    },
    {
        "filename": "scan_bad1.txt",
        "text": "[UNREADABLE] page 1 of medical intake form, scan quality too low.",
        "has_case": True,
        "unreadable": True,
    },
    {
        "filename": "scan_bad2.txt",
        "text": "%%%GARBLED%%% insurance correspondence, OCR failed.",
        "has_case": True,
        "unreadable": True,
    },
]


def seed(store):
    if store.cases:
        return  # already seeded

    case = store.create_case(
        "Doe v. Acme Trucking Co.",
        assigned_users=["pat_paralegal", "alex_attorney", "sam_admin", "dana_intake"],
    )

    for spec in DOCS:
        case_id = case.case_id if spec["has_case"] else None
        doc = store.upload_document(
            filename=spec["filename"],
            text=spec["text"],
            uploaded_by="dana_intake",
            case_id=case_id,
            readable=not spec.get("unreadable", False),
        )
        if case_id and not doc.is_duplicate and doc.readable:
            store.run_extraction(doc.doc_id, "dana_intake")
        elif case_id and doc.is_duplicate:
            pass  # duplicate: intentionally not processed, per FR-01
        elif case_id and not doc.readable:
            pass  # unreadable: intentionally not processed, per NFR-12

    return case
