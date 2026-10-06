"""Coverage for the Tracker's per-record preview dialog
(docs/superpowers/specs/2026-10-06-tracker-preview-dialog-design.md).

Firestore is faked at the seam tests/test_sidebar_redesign.py already uses
(firebase_dashboard.init_firebase -> a stand-in whose .stream() yields the
records). lualatex is faked by patching subprocess.run exactly like
tests/test_profile_export.py does - the compile is the one expensive thing
the dialog does, so counting those calls is how the cache is checked.

Dialog mechanics under AppTest: st.dialog is a fragment, so in a real
browser a widget inside it reruns only the dialog and keeps it open. AppTest
always executes the full script, so a bare .run() after clicking a button
inside the dialog closes it (the Preview opener is no longer "clicked").
Multi-step tests therefore re-click the opener before every .run(), the same
trick tests/test_draft_table.py documents for the Draft Table dialog.
"""
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


def saved_record(name="Acme Tracker Test"):
    return {
        "company_name": "Acme",
        "status": "Applied",
        "jd_text": "We need a backend engineer.",
        "notes": "",
        "resume_json": {
            "heading": {"name": name, "email": "a@b.c", "phone": "", "website": "", "linkedin": ""},
            "target_company": "Acme",
            "target_role": "Backend Engineer",
            "summary": "Engineer.",
            "education": [],
            "experience": [{"company": "Acme", "role": "Engineer", "time_duration": "2020-2024",
                            "company_location": "", "details": [{"description": "Did things"}]}],
            "projects": [],
            "patents": [],
            "skills": {"set1": {"title": "Skills", "items": ["Python"]}},
            "cover_letter": "",
        },
    }


def run_tracker(monkeypatch, records):
    docs = [_FakeDoc(f"doc{i}", data) for i, data in enumerate(records)]
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: _FakeFirestoreNode(docs))
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["active_view"] = "Tracker"
    at.session_state["logged_in"] = True
    at.session_state["user_email"] = EMAIL
    at.run()
    assert not at.exception
    return at


def preview_opener(at):
    openers = [b for b in at.button if b.key and b.key.startswith("preview_")]
    assert len(openers) == 1, [b.key for b in at.button]
    return openers[0]


def button(at, key):
    found = [b for b in at.button if b.key == key]
    assert len(found) == 1, [b.key for b in at.button]
    return found[0]


def test_row_has_preview_and_nothing_from_the_old_layout(monkeypatch):
    at = run_tracker(monkeypatch, [saved_record("Row Layout")])
    preview_opener(at)
    labels = {b.label for b in at.button}
    assert "Prep" not in labels
    assert "Radar" not in labels
    assert "View Data" not in labels
    # Editing moved into the dialog: nothing editable on the closed row.
    assert not [b for b in at.button if b.key and b.key.startswith("btn_")]
    assert not [t for t in at.text_area if t.key and t.key.startswith("notes_")]


def test_preview_compiles_once_and_offers_pdf_and_word(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))
    at = run_tracker(monkeypatch, [saved_record("Preview Compiles")])

    preview_opener(at).click().run()
    assert not at.exception
    assert len(calls) == 1 and calls[0][0] == "lualatex"

    # AppTest's DownloadButton proto carries a media URL, not the file name,
    # so the name itself is pinned by test_export_stem_matches_generator_naming.
    assert [d.key for d in at.download_button] == ["dlg_pdf_doc0", "dlg_docx_doc0"]
    # Editing lives in the dialog now.
    button(at, "dlg_update_doc0")
    button(at, "dlg_delete_doc0")
    assert [t for t in at.text_area if t.key == "dlg_notes_doc0"]


def test_reopening_the_same_record_does_not_recompile(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))
    at = run_tracker(monkeypatch, [saved_record("Preview Cached")])

    preview_opener(at).click().run()
    preview_opener(at).click().run()
    assert not at.exception
    assert len(calls) == 1


def test_switching_template_compiles_the_other_template(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))
    at = run_tracker(monkeypatch, [saved_record("Preview Template")])

    preview_opener(at).click().run()
    preview_opener(at).click()
    at.selectbox(key="dlg_tmpl_doc0").select("Business").run()
    assert not at.exception
    assert [c[-1] for c in calls] == ["main.tex", "elsa_main.tex"]


def test_missing_lualatex_keeps_word_download(monkeypatch):
    def no_lualatex(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "lualatex")

    monkeypatch.setattr("subprocess.run", no_lualatex)
    at = run_tracker(monkeypatch, [saved_record("Preview No LaTeX")])

    preview_opener(at).click().run()
    assert not at.exception
    assert [d.key for d in at.download_button] == ["dlg_docx_doc0"]
    assert any("LuaLaTeX is not installed" in e.value for e in at.error)


def test_delete_needs_confirmation(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))
    deleted = []
    monkeypatch.setattr(
        "firebase_dashboard.delete_application",
        lambda db, email, doc_id: deleted.append(doc_id) or True,
    )
    at = run_tracker(monkeypatch, [saved_record("Delete Confirm")])

    preview_opener(at).click().run()
    preview_opener(at).click()
    button(at, "dlg_delete_doc0").click().run()
    assert not at.exception
    assert deleted == []
    button(at, "dlg_delete_cancel_doc0")

    preview_opener(at).click()
    button(at, "dlg_delete_confirm_doc0").click().run()
    assert not at.exception
    assert deleted == ["doc0"]


def test_update_writes_status_and_notes(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))
    updates = []
    monkeypatch.setattr(
        "firebase_dashboard.update_application_status",
        lambda db, email, doc_id, status, notes: updates.append((doc_id, status, notes)) or True,
    )
    at = run_tracker(monkeypatch, [saved_record("Update Status")])

    preview_opener(at).click().run()
    preview_opener(at).click()
    at.selectbox(key="dlg_status_doc0").select("Interviewing")
    at.text_area(key="dlg_notes_doc0").input("Phone screen Friday")
    button(at, "dlg_update_doc0").click().run()
    assert not at.exception
    assert updates == [("doc0", "Interviewing", "Phone screen Friday")]


def test_export_stem_matches_generator_naming():
    """The tracker download must land in ~/Downloads under the same name the
    Generator's export used (app.export_file_name): company_role, then the
    candidate's own name, then a bare "Resume"."""
    from firebase_dashboard import _export_stem

    assert _export_stem(saved_record()["resume_json"]) == "Acme_Backend_Engineer"
    assert _export_stem({"target_company": "Acme Corp."}) == "Acme_Corp_Role"
    assert _export_stem({"heading": {"name": "Jane Doe"}}) == "Jane_Doe"
    assert _export_stem({}) == "Resume"


def test_prep_and_radar_helpers_are_gone():
    import ai
    import firebase_dashboard

    for name in ("predict_interview_questions", "analyze_skill_gap"):
        assert not hasattr(ai, name)
    for name in ("prep_interview_questions", "prep_skill_gap"):
        assert not hasattr(firebase_dashboard, name)
