"""Regression coverage for the Tracker recording guard's *wiring* in app.py.

workspace.should_record_application() itself is unit-tested across all four
boolean combinations in test_workspace.py. What isn't covered anywhere else is
the wiring around it inside app.py: that sync_application_to_tracker() only
flips st.session_state.tracked_application_id after save_application() has
actually run and returned success (never optimistically), that the guard
reads the real st.session_state.logged_in rather than a proxy, and that
clear_generated_outputs() resets the flag so a fresh Optimize run starts a
fresh application.

None of this touches Firestore. There is no .streamlit/secrets.toml on this
machine, so get_db() always returns None here — several assertions below
lean on exactly that fact to prove the guard never marks an application as
recorded without a write having actually been attempted.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

# Same anchoring rationale as test_app_smoke.py: AppTest.from_file resolves a
# relative path against this file's directory, not the process cwd.
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


def test_tracked_application_id_starts_none():
    at = run_app()
    assert not at.exception
    assert at.session_state["tracked_application_id"] is None


def test_download_while_logged_out_does_not_record():
    """The guard must read the real logged_in flag, not a proxy: an
    unauthenticated download must never flip tracked_application_id, and must
    never even reach Firestore — should_record_application() short-circuits
    before get_db() is called, so no error is surfaced either."""
    at = run_app(
        active_view="Generator",
        logged_in=False,
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Acme_Role_Resume.pdf"},
    )
    assert len(at.download_button) == 1
    at.download_button[0].click().run()
    assert not at.exception
    assert at.session_state["tracked_application_id"] is None
    assert len(at.error) == 0


def test_download_while_logged_in_does_not_optimistically_record():
    """tracked_application_id must only be set after save_application() has
    actually run and returned success — never just because the guard passed.
    Locally get_db() always returns None (no secrets.toml), so the write can
    never succeed; the flag must stay None even though the guard let the call
    through this time (proven by the "Tracker is unavailable" error, which
    only fires once should_record_application() has already returned True)."""
    at = run_app(
        active_view="Generator",
        logged_in=True,
        user_email="test@example.com",
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Acme_Role_Resume.pdf"},
    )
    at.download_button[0].click().run()
    assert not at.exception
    assert at.session_state["tracked_application_id"] is None
    assert any("Tracker is unavailable" in e.value for e in at.error)


def test_clear_generated_outputs_resets_tracked_application_id():
    """A fresh Optimize run must start a fresh application: clear_generated_outputs()
    is the shared reset point on both the PDF-import and Optimize paths. This drives
    it through the Advanced JSON Import button — the one caller that needs neither a
    live Gemini API key nor network access, so it stays hermetic."""
    at = run_app(
        active_view="Profile",
        show_advanced_tools=True,
        tracked_application_id="Acme",  # simulate an already-recorded application
    )
    assert at.session_state["tracked_application_id"] == "Acme"
    apply_buttons = [b for b in at.button if b.label == "Apply JSON Import"]
    assert len(apply_buttons) == 1
    apply_buttons[0].click().run()
    assert not at.exception
    assert at.session_state["tracked_application_id"] is None
