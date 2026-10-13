"""Coverage for "Reopen in Generator": a saved tracker record becomes a NEW
application in the Generator - its JD and its optimized resume loaded for
fine-tuning and regeneration, with the next download writing a fresh tracker
row rather than touching the old one.

Firestore and lualatex are faked the same way tests/test_tracker_preview.py
does. The dialog button sets st.session_state.pending_reopen_application and
reruns; app.py consumes it before any widget is drawn (same place
pending_reset is handled), so a single .run() after the click is enough.
"""
import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
EMAIL = "test@example.com"


class _FakeFirestoreNode:
    def __init__(self, docs):
        self._docs = docs

    def collection(self, *a, **k):
        return self

    def document(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def stream(self):
        return list(self._docs)

    def set(self, *a, **k):
        # autosave_profile() writes the profile on every run while logged in.
        return None


class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


def fake_lualatex(calls):
    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(cmd, cwd=None, capture_output=None, text=None, **kwargs):
        calls.append(cmd)
        with open(os.path.join(cwd, cmd[-1].replace(".tex", ".pdf")), "wb") as f:
            f.write(b"%PDF-1.4 fake")
        return FakeCompletedProcess()

    return run


PROFILE = {
    "heading": {"name": "Henry Reopen", "email": "a@b.c", "phone": "", "website": "", "linkedin": ""},
    "summary": "Engineer.",
    "education": [],
    "experience": [{"company": "Acme", "role": "Engineer", "time_duration": "2020-2024",
                    "company_location": "", "details": [{"description": "Did things"}]}],
    "projects": [], "patents": [],
    "skills": {"set1": {"title": "Skills", "items": ["Python"]}},
    "cover_letter": "", "target_company": "", "target_role": "",
}

OPTIMIZED = {
    **PROFILE,
    "target_company": "Acme",
    "target_role": "Backend Engineer",
    "summary": "Backend engineer tuned for Acme.",
}


def saved_record(resume_json=None, jd="We need a backend engineer at Acme."):
    return {
        "company_name": "Acme",
        "status": "Rejected",
        "jd_text": jd,
        "notes": "",
        "resume_json": OPTIMIZED if resume_json is None else resume_json,
    }


def run_tracker(monkeypatch, records, calls=None, **state):
    docs = [_FakeDoc(f"doc{i}", data) for i, data in enumerate(records)]
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: _FakeFirestoreNode(docs))
    monkeypatch.setattr("subprocess.run", fake_lualatex([] if calls is None else calls))
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["active_view"] = "Tracker"
    at.session_state["logged_in"] = True
    at.session_state["user_email"] = EMAIL
    at.session_state["resume_data"] = json.loads(json.dumps(PROFILE))
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception
    return at


def button(at, key):
    found = [b for b in at.button if b.key == key]
    assert len(found) == 1, [b.key for b in at.button]
    return found[0]


def preview_opener(at):
    return [b for b in at.button if b.key and b.key.startswith("preview_")][0]


def reopen(at):
    preview_opener(at).click().run()
    assert not at.exception
    # Re-stage the opener click: the dialog only renders on a run where the
    # Preview button reads as clicked (see tests/test_draft_table.py).
    preview_opener(at).click()
    button(at, "dlg_reopen_doc0").click().run()
    assert not at.exception
    return at


def test_reopen_loads_jd_and_resume_into_generator_as_a_new_application(monkeypatch):
    at = run_tracker(
        monkeypatch, [saved_record()],
        # Leftovers from a previous application that must not survive.
        tracked_application_id="Globex",
        jd_text="old globex jd",
        resume_preview_bytes=b"%PDF-old",
        resume_dl_data={"bytes": b"%PDF-old", "name": "Globex_Role_Resume.pdf"},
        application_chat=[{"role": "user", "content": "old question"}],
    )
    reopen(at)

    assert at.session_state["active_view"] == "Generator"
    assert at.session_state["jd_text"] == "We need a backend engineer at Acme."
    assert at.session_state["optimized_resume_data"] == OPTIMIZED
    # A new application: nothing recorded yet, no old chat - and the PDF is
    # the reopened version's, not whatever the previous application left.
    assert at.session_state["tracked_application_id"] is None
    assert at.session_state["resume_preview_bytes"] == b"%PDF-1.4 fake"
    assert at.session_state["resume_dl_data"]["bytes"] == b"%PDF-1.4 fake"
    assert at.session_state["application_chat"] == []
    # The Career Profile itself is untouched.
    assert at.session_state["resume_data"] == PROFILE
    # The JD widget shows the reopened JD (it is keyed off base_editor_key).
    jd_key = f"jd_input_{at.session_state['base_editor_key']}"
    assert at.text_area(key=jd_key).value == "We need a backend engineer at Acme."
    banner = at.session_state["result_banner"]
    assert "Acme" in banner["title"]


def test_reopened_result_is_not_flagged_stale(monkeypatch):
    """The saved resume is deliberately a snapshot of an older optimize run;
    the user wants to refine THAT, so Generate PDF must not refuse it as
    stale against today's profile."""
    at = run_tracker(monkeypatch, [saved_record()])
    reopen(at)
    assert at.session_state["optimized_source_snapshot"] == json.dumps(
        at.session_state["resume_data"], ensure_ascii=False, sort_keys=True
    )
    assert not any("stale" in e.value.lower() for e in at.error)


def test_download_after_reopen_writes_a_new_tracker_row(monkeypatch):
    saved = []
    monkeypatch.setattr(
        "firebase_dashboard.save_application",
        lambda db, email, company, resume_json, jd_text="": saved.append((company, jd_text)) or True,
    )
    at = run_tracker(monkeypatch, [saved_record()], tracked_application_id="doc0")
    reopen(at)

    # No Generate PDF click needed: reopening already produced the PDF.
    pdf_buttons = [d for d in at.download_button if d.key == "dl_pdf"]
    assert len(pdf_buttons) == 1
    pdf_buttons[0].click().run()
    assert not at.exception
    assert saved == [("Acme", "We need a backend engineer at Acme.")]
    assert at.session_state["tracked_application_id"] == "Acme"


def test_reopen_with_unusable_resume_json_still_loads_the_jd(monkeypatch):
    at = run_tracker(monkeypatch, [saved_record(resume_json="not a dict")])
    reopen(at)
    assert at.session_state["active_view"] == "Generator"
    assert at.session_state["optimized_resume_data"] is None
    assert at.session_state["jd_text"] == "We need a backend engineer at Acme."
    # Nothing to render, so no PDF - the preview falls back to the profile.
    assert at.session_state["resume_preview_bytes"] is None


def test_reopen_reuses_the_pdf_the_dialog_already_compiled(monkeypatch):
    """The dialog compiled this exact PDF a moment ago; the Generator
    preview must show it straight away, not make the user wait for lualatex
    a second time."""
    calls = []
    at = run_tracker(monkeypatch, [saved_record()], calls=calls)
    reopen(at)
    assert [c[-1] for c in calls] == ["main.tex"]
    assert at.session_state["resume_preview_bytes"] == b"%PDF-1.4 fake"


def test_reopen_uses_the_template_the_dialog_was_showing(monkeypatch):
    calls = []
    at = run_tracker(monkeypatch, [saved_record()], calls=calls, preferred_template="Business")
    reopen(at)
    assert [c[-1] for c in calls] == ["elsa_main.tex"]
    assert at.selectbox(key="tm").value == "Business"


def test_reopen_compiles_when_the_dialog_pdf_is_not_cached(monkeypatch):
    """E.g. the dialog's compile failed (failures are not cached) - the
    reopen still tries on its own rather than leaving the preview empty."""
    calls = []
    at = run_tracker(monkeypatch, [saved_record()], calls=calls)
    preview_opener(at).click().run()
    at.session_state["tracker_pdf_cache"] = {}
    preview_opener(at).click()
    button(at, "dlg_reopen_doc0").click().run()
    assert not at.exception
    assert [c[-1] for c in calls] == ["main.tex", "main.tex"]
    assert at.session_state["resume_preview_bytes"] == b"%PDF-1.4 fake"


def test_reopen_also_prepares_the_cover_letter(monkeypatch):
    calls = []
    record = saved_record(resume_json={**OPTIMIZED, "cover_letter": "Dear Acme team, ..."})
    at = run_tracker(monkeypatch, [record], calls=calls)
    reopen(at)
    assert [c[-1] for c in calls] == ["main.tex", "c.tex"]
    assert at.session_state["cover_letter_preview_bytes"] == b"%PDF-1.4 fake"
