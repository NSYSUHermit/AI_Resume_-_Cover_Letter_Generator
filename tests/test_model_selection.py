"""Choosing a Gemini model in the app (app.py).

ai.py decides what a key can run (tests/test_ai_models.py); this covers what
the app does with that: the Step 1 card's Test key -> pick -> Save key flow,
the Settings switcher in the sidebar, the chain every AI call receives,
fallback notes reaching the result banner, and persistence for signed-in
users.

ai.check_models and the ai.* calls are stubbed at the module attribute, which
works because app.py calls them through `ai.`.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

import ai

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
EMAIL = "test@example.com"

RESULTS = [
    {"model": "gemini-2.5-flash", "status": ai.BUSY, "reason": "quota used up for now"},
    {"model": "gemini-2.5-flash-lite", "status": ai.OK, "reason": "works"},
    {"model": "gemini-2.5-pro", "status": ai.NOT_FREE, "reason": "not on the free tier"},
]


class _FakeFirestore:
    """Chain methods return self; .set() records the write."""

    def __init__(self):
        self.writes = []

    def collection(self, *a, **k):
        return self

    def document(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def stream(self):
        return []

    def set(self, data, merge=False):
        self.writes.append(data)


def run_app(monkeypatch, results=RESULTS, key_ok=True, **state):
    monkeypatch.setattr("ai.check_models", lambda api_key: (key_ok, "checked", list(results)))
    fake_db = _FakeFirestore()
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: fake_db)
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception
    return at, fake_db


def button(at, label):
    found = [b for b in at.button if b.label == label]
    assert len(found) == 1, [b.label for b in at.button]
    return found[0]


def enter_and_test_key(at, key="AIza-test"):
    at.text_input(key="api_key_input").input(key).run()
    button(at, "Test key").click().run()
    assert not at.exception


def model_writes(fake_db):
    return [w for w in fake_db.writes if "gemini_model" in w]


# --- Step 1 card --------------------------------------------------------------

def test_testing_a_key_lists_models_and_preselects_one_that_works(monkeypatch):
    at, _ = run_app(monkeypatch)
    enter_and_test_key(at)

    text = " ".join(m.value for m in at.markdown)
    for r in RESULTS:
        assert r["model"] in text
    # Only usable models are offered; one that answered just now is preselected.
    picker = at.selectbox(key="setup_model_choice")
    assert picker.options == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    assert picker.value == "gemini-2.5-flash-lite"
    # Testing alone saves nothing.
    assert at.session_state["api_key"] == ""


def test_save_key_stores_the_key_and_the_chosen_model(monkeypatch):
    at, _ = run_app(monkeypatch)
    enter_and_test_key(at)
    at.selectbox(key="setup_model_choice").select("gemini-2.5-flash").run()
    button(at, "Save key").click().run()
    assert not at.exception

    assert at.session_state["api_key"] == "AIza-test"
    assert at.session_state["gemini_model"] == "gemini-2.5-flash"
    assert at.session_state["gemini_models"] == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    # The setup card is gone once a key is saved.
    assert not [t for t in at.text_input if t.key == "api_key_input"]


def test_no_usable_model_offers_no_save(monkeypatch):
    at, _ = run_app(monkeypatch, results=[RESULTS[2]])
    enter_and_test_key(at)
    assert not [b for b in at.button if b.label == "Save key"]
    assert not [s for s in at.selectbox if s.key == "setup_model_choice"]


def test_editing_the_key_after_testing_hides_the_old_results(monkeypatch):
    at, _ = run_app(monkeypatch)
    enter_and_test_key(at)
    at.text_input(key="api_key_input").input("AIza-other").run()
    assert not [b for b in at.button if b.label == "Save key"]


def test_signed_in_save_persists_the_model_choice(monkeypatch):
    at, fake_db = run_app(monkeypatch, logged_in=True, user_email=EMAIL)
    enter_and_test_key(at)
    button(at, "Save key").click().run()
    assert not at.exception
    assert model_writes(fake_db)[-1] == {
        "gemini_model": "gemini-2.5-flash-lite",
        "gemini_models": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    }


# --- AI calls -------------------------------------------------------------------

def test_optimize_passes_the_chosen_model_first_then_the_fallbacks(monkeypatch):
    seen = []

    def screen(jd_text, api_key, models=None, on_fallback=None):
        seen.append(models)
        return {"target_company": "Acme", "target_role": "Engineer", "keywords": []}

    def rewrite(jd_text, resume, prompt, api_key, models=None, on_fallback=None):
        seen.append(models)
        return {"optimized_resume": {"summary": "x"}, "changelog": "", "suggested_metrics": []}

    monkeypatch.setattr("ai.screen_job_description", screen)
    monkeypatch.setattr("ai.rewrite_resume", rewrite)
    at, _ = run_app(
        monkeypatch, active_view="Generator", api_key="AIza-test", jd_text="A" * 60,
        gemini_model="gemini-2.5-flash-lite", gemini_models=["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    )
    button(at, "Optimize Resume").click().run()
    assert not at.exception
    assert seen == [["gemini-2.5-flash-lite", "gemini-2.5-flash"]] * 2


def test_a_fallback_is_reported_in_the_result_banner(monkeypatch):
    def screen(jd_text, api_key, models=None, on_fallback=None):
        on_fallback("gemini-2.5-flash-lite", [("gemini-2.5-flash", "quota used up for now")])
        return {"target_company": "Acme", "target_role": "Engineer", "keywords": []}

    monkeypatch.setattr("ai.screen_job_description", screen)
    monkeypatch.setattr(
        "ai.rewrite_resume",
        lambda *a, **k: {"optimized_resume": {"summary": "x"}, "changelog": "", "suggested_metrics": []},
    )
    at, _ = run_app(
        monkeypatch, active_view="Generator", api_key="AIza-test", jd_text="A" * 60,
        gemini_model="gemini-2.5-flash", gemini_models=["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    )
    button(at, "Optimize Resume").click().run()
    assert not at.exception
    details = at.session_state["result_banner"]["details"]
    assert "Answered by gemini-2.5-flash-lite (gemini-2.5-flash: quota used up for now)" in details


def test_no_check_yet_falls_back_to_the_default_model(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "ai.screen_job_description",
        lambda jd, key, models=None, on_fallback=None: seen.append(models) or {"visa_blocked": True},
    )
    at, _ = run_app(monkeypatch, active_view="Generator", api_key="AIza-old", jd_text="A" * 60)
    button(at, "Optimize Resume").click().run()
    assert seen == [[ai.GEMINI_MODEL]]


# --- Settings -------------------------------------------------------------------

def test_settings_switches_the_model_and_persists_it(monkeypatch):
    at, fake_db = run_app(
        monkeypatch, api_key="AIza-test", logged_in=True, user_email=EMAIL,
        gemini_model="gemini-2.5-flash", gemini_models=["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    )
    at.selectbox(key="settings_model").select("gemini-2.5-flash-lite").run()
    assert not at.exception
    assert at.session_state["gemini_model"] == "gemini-2.5-flash-lite"
    assert model_writes(fake_db)[-1]["gemini_model"] == "gemini-2.5-flash-lite"
    assert at.selectbox(key="settings_model").value == "gemini-2.5-flash-lite"


def test_retest_switches_away_from_a_model_the_key_can_no_longer_use(monkeypatch):
    at, _ = run_app(
        monkeypatch, api_key="AIza-test",
        gemini_model="gemini-2.5-pro", gemini_models=["gemini-2.5-pro"],
    )
    at.sidebar.button(key="retest_models").click().run()
    assert not at.exception
    assert at.session_state["gemini_model"] == "gemini-2.5-flash-lite"
    assert at.session_state["gemini_models"] == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    assert at.selectbox(key="settings_model").value == "gemini-2.5-flash-lite"


def test_retest_keeps_a_choice_that_still_works(monkeypatch):
    at, _ = run_app(
        monkeypatch, api_key="AIza-test",
        gemini_model="gemini-2.5-flash", gemini_models=["gemini-2.5-flash"],
    )
    at.sidebar.button(key="retest_models").click().run()
    assert not at.exception
    assert at.session_state["gemini_model"] == "gemini-2.5-flash"


# --- Login / logout ---------------------------------------------------------------

def login(at):
    [email_box] = [t for t in at.sidebar.text_input if t.label == "Email"]
    email_box.input(EMAIL)
    [login_button] = [b for b in at.sidebar.button if b.label == "Login"]
    login_button.click().run()
    assert not at.exception


def test_login_restores_the_saved_model_choice(monkeypatch):
    monkeypatch.setattr("firebase_dashboard.authenticate_user", lambda db, e, p: (True, "ok"))
    monkeypatch.setattr(
        "firebase_dashboard.load_user_profile",
        lambda db, email: {"api_key": "AIza-saved", "gemini_model": "gemini-2.5-flash-lite",
                           "gemini_models": ["gemini-2.5-flash", "gemini-2.5-flash-lite"]},
    )
    at, fake_db = run_app(monkeypatch)
    login(at)
    assert at.session_state["gemini_model"] == "gemini-2.5-flash-lite"
    assert at.session_state["gemini_models"] == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    assert model_writes(fake_db) == []


def test_login_ignores_a_malformed_saved_model(monkeypatch):
    monkeypatch.setattr("firebase_dashboard.authenticate_user", lambda db, e, p: (True, "ok"))
    monkeypatch.setattr(
        "firebase_dashboard.load_user_profile",
        lambda db, email: {"gemini_model": 42, "gemini_models": "gemini-2.5-flash"},
    )
    at, _ = run_app(monkeypatch)
    login(at)
    assert at.session_state["gemini_model"] is None
    assert at.session_state["gemini_models"] == []


def test_logout_forgets_the_model_choice(monkeypatch):
    at, _ = run_app(
        monkeypatch, api_key="AIza-test", logged_in=True, user_email=EMAIL,
        gemini_model="gemini-2.5-flash-lite", gemini_models=["gemini-2.5-flash-lite"],
    )
    button(at, "Logout").click().run()
    assert not at.exception
    assert at.session_state["gemini_model"] is None
    assert at.session_state["gemini_models"] == []
