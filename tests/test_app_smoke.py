from pathlib import Path

from streamlit.testing.v1 import AppTest

# AppTest.from_file() resolves a relative path against the directory of the
# file that calls it (this test file, in tests/), not the process cwd — so a
# bare "app.py" can never resolve to the repo root from here. Anchor off
# __file__ instead.
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
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
