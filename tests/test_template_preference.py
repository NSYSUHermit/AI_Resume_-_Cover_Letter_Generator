"""The Template choice is remembered: whatever the user last picked becomes
the default, so a Business user is not switching away from Tech every time.

Two layers, two failure modes:

1. In-session. `tm` is a widget key, and Streamlit drops widget keys on any
   rerun where the widget is not rendered - so a Generator -> Profile ->
   Generator round trip used to snap the selectbox back to "Tech". The
   durable copy is `preferred_template`, the same mirror pattern jd_text uses
   (see tests/test_generator_workspace.py).
2. Across sessions. Signed-in users get it written to their Firestore
   base_profile doc and restored on login. Signed-out users have no profile
   to write to, and must never touch Firestore.

Firestore is faked at firebase_dashboard.init_firebase, the seam
tests/test_sidebar_redesign.py and tests/test_tracker_preview.py already use.
"""
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

import firebase_dashboard

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
EMAIL = "test@example.com"


class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _FakeFirestore:
    """Every chain method returns self; .set() records the write and the
    path it was made on, .stream() yields the given tracker records."""

    def __init__(self, records=()):
        self.path = []
        self.writes = []
        self.docs = [_FakeDoc(f"doc{i}", data) for i, data in enumerate(records)]

    def collection(self, name):
        self.path.append(name)
        return self

    def document(self, name=None):
        self.path.append(name)
        return self

    def order_by(self, *a, **k):
        return self

    def stream(self):
        self.path = []
        return list(self.docs)

    def set(self, data, merge=False):
        self.writes.append((tuple(self.path), data, merge))
        self.path = []


def run_app(monkeypatch, records=(), **session_overrides):
    fake_db = _FakeFirestore(records)
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: fake_db)
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception
    return at, fake_db


def template_writes(fake_db):
    return [data for _, data, _ in fake_db.writes if "preferred_template" in data]


def test_new_session_defaults_to_tech(monkeypatch):
    at, _ = run_app(monkeypatch, active_view="Generator")
    assert at.selectbox(key="tm").value == "Tech"


def test_template_choice_survives_a_profile_round_trip(monkeypatch):
    at, _ = run_app(monkeypatch, active_view="Generator")
    at.selectbox(key="tm").select("Business").run()
    assert not at.exception

    at.sidebar.button(key="nav_Profile").click().run()
    at.sidebar.button(key="nav_Generator").click().run()
    assert at.session_state["active_view"] == "Generator"
    assert at.selectbox(key="tm").value == "Business"


def test_signed_in_choice_is_saved_to_the_profile(monkeypatch):
    at, fake_db = run_app(monkeypatch, active_view="Generator", logged_in=True, user_email=EMAIL)
    at.selectbox(key="tm").select("Business").run()
    assert not at.exception

    path, data, merge = fake_db.writes[-1]
    assert data == {"preferred_template": "Business"}
    # merge=True, or the write would wipe base_resume / custom_prompt / api_key
    # stored on the same document.
    assert merge is True
    assert path == ("users", EMAIL, "profile", "base_profile")


def test_signed_out_choice_never_touches_firestore(monkeypatch):
    at, fake_db = run_app(monkeypatch, active_view="Generator")
    at.selectbox(key="tm").select("Business").run()
    assert not at.exception
    assert fake_db.writes == []
    assert at.session_state["preferred_template"] == "Business"


def test_login_restores_the_saved_template(monkeypatch):
    profile = {
        "heading": {"name": "Ada", "email": "", "phone": "", "website": "", "linkedin": ""},
        "summary": "Engineer.",
        "experience": [{"company": "Acme", "role": "Engineer", "time_duration": "2020",
                        "company_location": "", "details": [{"description": "Did things"}]}],
    }
    monkeypatch.setattr("firebase_dashboard.authenticate_user", lambda db, e, p: (True, "ok"))
    monkeypatch.setattr(
        "firebase_dashboard.load_user_profile",
        lambda db, email: (profile, "", "", "Business"),
    )
    at, fake_db = run_app(monkeypatch)

    [email_box] = [t for t in at.sidebar.text_input if t.label == "Email"]
    [password_box] = [t for t in at.sidebar.text_input if t.label == "Password"]
    email_box.input(EMAIL)
    password_box.input("hunter22")
    [login] = [b for b in at.sidebar.button if b.label == "Login"]
    login.click().run()
    assert not at.exception

    assert at.session_state["logged_in"] is True
    assert at.session_state["active_view"] == "Generator"
    assert at.selectbox(key="tm").value == "Business"
    # Restoring is a read; it must not echo the value straight back.
    assert template_writes(fake_db) == []


def test_unknown_saved_template_falls_back_to_tech(monkeypatch):
    monkeypatch.setattr("firebase_dashboard.authenticate_user", lambda db, e, p: (True, "ok"))
    monkeypatch.setattr(
        "firebase_dashboard.load_user_profile",
        lambda db, email: (None, None, None, "Retired Template"),
    )
    at, _ = run_app(monkeypatch)
    [email_box] = [t for t in at.sidebar.text_input if t.label == "Email"]
    email_box.input(EMAIL)
    [login] = [b for b in at.sidebar.button if b.label == "Login"]
    login.click().run()
    assert not at.exception
    assert at.session_state["preferred_template"] == "Tech"


def test_logout_forgets_the_previous_users_template(monkeypatch):
    at, _ = run_app(
        monkeypatch, active_view="Generator", logged_in=True, user_email=EMAIL,
        preferred_template="Business",
    )
    assert at.selectbox(key="tm").value == "Business"

    [logout] = [b for b in at.sidebar.button if b.label == "Logout"]
    logout.click().run()
    assert not at.exception
    assert at.session_state["preferred_template"] == "Tech"


def test_load_user_profile_returns_the_saved_template():
    class Doc:
        exists = True

        def to_dict(self):
            return {"base_resume": {"summary": "x"}, "custom_prompt": "p",
                    "api_key": "k", "preferred_template": "Business"}

    class Db:
        def collection(self, *a):
            return self

        def document(self, *a):
            return self

        def get(self):
            return Doc()

    assert firebase_dashboard.load_user_profile(Db(), EMAIL) == ({"summary": "x"}, "p", "k", "Business")


# --- Tracker preview dialog -------------------------------------------------
# Same fakes as tests/test_tracker_preview.py: lualatex is faked at
# subprocess.run, and every compile is recorded so the template it used is
# visible as the .tex file name.

def fake_lualatex(calls):
    class Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(cmd, cwd=None, **kwargs):
        calls.append(cmd[-1])
        with open(os.path.join(cwd, cmd[-1].replace(".tex", ".pdf")), "wb") as f:
            f.write(b"%PDF-1.4 fake")
        return Done()

    return run


SAVED_RECORD = {
    "company_name": "Acme",
    "status": "Applied",
    "jd_text": "",
    "notes": "",
    "resume_json": {
        "heading": {"name": "Template Pref", "email": "", "phone": "", "website": "", "linkedin": ""},
        "summary": "Engineer.",
        "education": [],
        "experience": [{"company": "Acme", "role": "Engineer", "time_duration": "2020",
                        "company_location": "", "details": [{"description": "Did things"}]}],
        "projects": [],
        "patents": [],
        "skills": {"set1": {"title": "Skills", "items": ["Python"]}},
        "cover_letter": "",
    },
}


def open_dialog(at):
    [opener] = [b for b in at.button if b.key and b.key.startswith("preview_")]
    return opener.click()


def test_tracker_dialog_opens_on_the_preferred_template(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))
    at, _ = run_app(
        monkeypatch, records=[SAVED_RECORD], active_view="Tracker",
        logged_in=True, user_email=EMAIL, preferred_template="Business",
    )
    open_dialog(at).run()
    assert not at.exception
    assert at.selectbox(key="dlg_tmpl_doc0").value == "Business"
    assert calls == ["elsa_main.tex"]


def test_tracker_dialog_choice_becomes_the_preference(monkeypatch):
    monkeypatch.setattr("subprocess.run", fake_lualatex([]))
    at, fake_db = run_app(
        monkeypatch, records=[SAVED_RECORD], active_view="Tracker",
        logged_in=True, user_email=EMAIL,
    )
    open_dialog(at).run()
    open_dialog(at)
    at.selectbox(key="dlg_tmpl_doc0").select("Business").run()
    assert not at.exception
    assert at.session_state["preferred_template"] == "Business"
    assert template_writes(fake_db) == [{"preferred_template": "Business"}]
