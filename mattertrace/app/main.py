"""
MatterTrace prototype - Flask app.

Run with:  python -m app.main
Then open http://127.0.0.1:5000

Login is a simple "pick your username" dropdown (no real auth) since this is
a bounded prototype demonstrating the control logic, not a production auth
system. Seeded users (see store.py):
  dana_intake     (role: intake)
  pat_paralegal   (role: paralegal)
  alex_attorney   (role: attorney)
  sam_admin       (role: administrator)
"""
from flask import Flask, render_template, request, redirect, url_for, session, flash
from app.store import store, PermissionError_
from app import extraction
from app.seed_demo import seed as seed_demo

app = Flask(__name__)
app.secret_key = "prototype-only-not-for-production"
seed_demo(store)


def current_user():
    return session.get("username")


@app.context_processor
def inject_user():
    username = current_user()
    user = store.users.get(username) if username else None
    return {"current_username": username, "current_role": user.role if user else None}


@app.route("/")
def index():
    return render_template("index.html", cases=store.cases.values())


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        session["username"] = request.form["username"]
        return redirect(url_for("index"))
    return render_template("login.html", users=store.users.values())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/case/new", methods=["GET", "POST"])
def new_case():
    if request.method == "POST":
        title = request.form["title"]
        assigned = request.form.getlist("assigned_users")
        case = store.create_case(title, assigned)
        return redirect(url_for("case_detail", case_id=case.case_id))
    return render_template("new_case.html", users=store.users.values())


@app.route("/case/<case_id>")
def case_detail(case_id):
    try:
        store.require_case_access(current_user(), case_id)
    except PermissionError_ as e:
        flash(str(e), "error")
        return redirect(url_for("index"))
    case = store.cases[case_id]
    docs = [d for d in store.documents.values() if d.case_id == case_id]
    entries = [e for e in store.entries.values() if e.case_id == case_id]
    suggested = [e for e in entries if e.status == "suggested"]
    checked = [e for e in entries if e.status in ("checked",)]
    escalated = [e for e in entries if e.status == "escalated"]
    missing = [m for m in store.missing_records.values() if m.case_id == case_id]
    return render_template(
        "case_detail.html", case=case, docs=docs, suggested=suggested,
        checked=checked, escalated=escalated, missing=missing,
        approved=store.case_approved.get(case_id, False),
    )


@app.route("/case/<case_id>/upload", methods=["POST"])
def upload_doc(case_id):
    filename = request.form["filename"]
    text = request.form["text"]
    readable = "unreadable" not in request.form
    doc = store.upload_document(filename, text, current_user(), case_id=case_id, readable=readable)
    if doc.is_duplicate:
        flash(f"Document '{filename}' flagged as a DUPLICATE and will not be processed.", "warning")
    elif not doc.readable:
        flash(f"Document '{filename}' flagged UNREADABLE - sent for a person to look at.", "warning")
    else:
        new_entries = store.run_extraction(doc.doc_id, current_user())
        flash(f"Document '{filename}' processed: {len(new_entries)} suggested entries.", "success")
    return redirect(url_for("case_detail", case_id=case_id))


@app.route("/unassigned")
def unassigned_docs():
    docs = [store.documents[d] for d in store.unassigned_docs]
    return render_template("unassigned.html", docs=docs, cases=store.cases.values())


@app.route("/unassigned/<doc_id>/assign", methods=["POST"])
def assign_doc(doc_id):
    case_id = request.form["case_id"]
    store.assign_case_to_doc(doc_id, case_id, current_user())
    store.run_extraction(doc_id, current_user())
    flash("Document assigned and processed.", "success")
    return redirect(url_for("unassigned_docs"))


@app.route("/entry/<entry_id>/review", methods=["POST"])
def review_entry(entry_id):
    action = request.form["action"]
    edits = {
        "description": request.form.get("description"),
        "date": request.form.get("date"),
        "parties": request.form.get("parties"),
        "amount": request.form.get("amount"),
    }
    try:
        entry = store.review_entry(entry_id, current_user(), action, edits=edits)
        if entry.status == "escalated":
            flash("This item is risky (mismatch/court/deadline) and was routed to the attorney.", "warning")
        else:
            flash(f"Entry {action}d.", "success")
    except PermissionError_ as e:
        flash(str(e), "error")
    return redirect(url_for("case_detail", case_id=request.form["case_id"]))


@app.route("/case/<case_id>/attorney")
def attorney_queue(case_id):
    try:
        store.require_role(current_user(), ["attorney", "administrator"])
        store.require_case_access(current_user(), case_id)
    except PermissionError_ as e:
        flash(str(e), "error")
        return redirect(url_for("case_detail", case_id=case_id))
    case = store.cases[case_id]
    queue = store.attorney_queue(case_id)
    return render_template("attorney_queue.html", case=case, queue=queue,
                            approved=store.case_approved.get(case_id, False))


@app.route("/entry/<entry_id>/attorney_resolve", methods=["POST"])
def attorney_resolve(entry_id):
    decision = request.form["decision"]
    edits = {"description": request.form.get("description")}
    try:
        store.attorney_resolve(entry_id, current_user(), decision, edits=edits)
        flash("Item resolved by attorney.", "success")
    except PermissionError_ as e:
        flash(str(e), "error")
    return redirect(url_for("attorney_queue", case_id=request.form["case_id"]))


@app.route("/case/<case_id>/approve", methods=["POST"])
def approve_case(case_id):
    try:
        store.approve_timeline(case_id, current_user())
        flash("Timeline approved by attorney.", "success")
    except (PermissionError_, ValueError) as e:
        flash(str(e), "error")
    return redirect(url_for("case_detail", case_id=case_id))


@app.route("/case/<case_id>/export")
def export_timeline(case_id):
    try:
        store.require_case_access(current_user(), case_id)
    except PermissionError_ as e:
        flash(str(e), "error")
        return redirect(url_for("index"))
    report = store.export_timeline(case_id)
    return render_template("export.html", report=report, case=store.cases[case_id])


@app.route("/ask", methods=["GET", "POST"])
def ask_question():
    """FR-12: refuse legal-advice / strategy / valuation / negotiation questions."""
    answer = None
    if request.method == "POST":
        question = request.form["question"]
        if store.check_legal_advice_request(question):
            answer = ("MatterTrace cannot give legal advice, case valuation, strategy, "
                      "or negotiation guidance. Please direct this question to an attorney.")
        else:
            answer = ("MatterTrace only builds case timelines from documents. "
                      "This question is outside that scope - please ask a case-specific "
                      "timeline question, or direct it to case staff.")
    return render_template("ask.html", answer=answer)


@app.route("/activity_log")
def activity_log():
    store.require_role(current_user(), ["administrator", "attorney", "paralegal", "intake"])
    return render_template("activity_log.html", log=reversed(store.activity_log))


if __name__ == "__main__":
    import os
    debug_mode = os.environ.get("MATTERTRACE_DEBUG", "0") == "1"
    app.run(debug=debug_mode, port=5000, use_reloader=False)
