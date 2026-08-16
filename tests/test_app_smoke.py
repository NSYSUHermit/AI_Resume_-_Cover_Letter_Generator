from pathlib import Path

from streamlit.testing.v1 import AppTest

# AppTest.from_file() resolves a relative path against the directory of the
# file that calls it (this test file, in tests/), not the process cwd — so a
# bare "app.py" can never resolve to the repo root from here. Anchor off
# __file__ instead.
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


def test_app_runs_without_exception():
    at = run_app()
    assert not at.exception


def test_sidebar_has_exactly_three_nav_buttons():
    at = run_app()
    nav_keys = [b.key for b in at.sidebar.button if b.key and b.key.startswith("nav_")]
    assert nav_keys == ["nav_Profile", "nav_Generator", "nav_Tracker"]


def test_empty_profile_lands_on_career_profile():
    at = run_app()
    assert at.session_state.active_view == "Profile"


def test_clicking_tracker_switches_view():
    at = run_app()
    at.sidebar.button(key="nav_Tracker").click().run()
    assert at.session_state.active_view == "Tracker"


def test_clicking_generator_switches_view():
    at = run_app()
    at.sidebar.button(key="nav_Generator").click().run()
    assert at.session_state.active_view == "Generator"


def test_logout_recomputes_active_view_to_profile():
    """Finding 3: logging out from Generator with a populated profile must
    land back on Profile, not stay on Generator now showing "Your Career
    Profile is empty" -- exactly the case workspace.initial_view() exists to
    route around. clear_user_session() resets resume_data to empty; without
    also recomputing active_view alongside it, the stale "Generator" value
    would survive the reset untouched."""
    at = run_app(
        active_view="Generator",
        logged_in=True,
        user_email="test@example.com",
        resume_data={"heading": {"name": "Jane Doe"}},
    )
    assert at.session_state["active_view"] == "Generator"
    logout_buttons = [b for b in at.button if b.label == "Logout"]
    assert len(logout_buttons) == 1
    logout_buttons[0].click().run()
    assert not at.exception
    assert at.session_state["active_view"] == "Profile"


def test_density_pass_css_values_are_pinned():
    """UI Task 4's global density pass (design doc "全域縮小間距與內邊距") lives
    entirely in app.py's single stylesheet block and applies to every view,
    not just Generator - this deliberately runs on a fresh session (no
    active_view override) rather than duplicating a Generator-specific check.
    Regression guard in the same spirit as
    test_progress_strip.py's test_main_container_padding_is_pinned: if
    these literals drift back toward their pre-Task-4 values, the density
    pass has silently been undone. Cannot assert anything about how this
    actually looks - that's the visual judgement call listed as unverified in
    this task's own report."""
    at = run_app()
    assert not at.exception
    style_matches = [m for m in at.markdown if "stMainBlockContainer" in m.value]
    assert len(style_matches) == 1
    css = style_matches[0].value
    # padding-top is a DIFFERENT pinned value (the top status strip's own
    # headroom, Generator-view-only - already guarded in
    # test_progress_strip.py) - deliberately not re-asserted here so this
    # test cannot pass for the wrong reason if that one is ever legitimately
    # revised. Also why this test does not care that
    # a fresh session (no active_view override, as used below) lands on
    # Profile rather than Generator - padding-top differs by view now, but
    # nothing this test actually checks does.
    assert "padding-bottom: 2rem;" in css
    assert '[data-testid="stVerticalBlock"]' in css
    assert "gap: 0.6rem !important;" in css
    assert '[data-testid="stHorizontalBlock"]' in css
    assert "gap: 0.75rem !important;" in css


def test_reset_all_data_recomputes_active_view_to_profile():
    """Finding 3, same shape via the other clear_user_session() caller: the
    Reset All Data button (Settings expander) sets pending_reset and reruns;
    clear_user_session() runs on the next script run, before any widget is
    created. Same invariant, same fix, different trigger."""
    at = run_app(active_view="Generator", resume_data={"heading": {"name": "Jane Doe"}})
    reset_buttons = [b for b in at.button if b.label == "Reset All Data"]
    assert len(reset_buttons) == 1
    reset_buttons[0].click().run()
    assert not at.exception
    assert at.session_state["active_view"] == "Profile"
