"""Regression coverage for render_generator_workspace()'s left column.

Two invariants live here that nothing else in the suite touches:

1. The JD and Custom Strategy mirror (app.py, inside render_generator_workspace):
   both text areas read their `value=` from a durable session key
   (`jd_text` / `custom_prompt`) and write straight back to it after every
   render. Streamlit drops a widget's own entry from session_state on any
   rerun where the widget is not instantiated — e.g. switching to a
   different workspace, where render_generator_workspace() is not called at
   all — which is what silently emptied the JD before this mirror existed.
   This branch physically moved that code into render_generator_workspace()
   and changed the label, height and placeholder around it; nothing else in
   the 25 pre-existing tests exercises it, so deleting the
   `st.session_state.jd_text = jd` line, or hard-coding the widget key
   instead of keying it off base_editor_key, would ship with every other
   test green. The two tests below reproduce the original bug's exact
   trigger (a Generator -> Profile -> Generator round trip) and were each
   confirmed, before being committed, to fail against a temporarily
   reintroduced copy of both regressions.
2. Generate PDF (render_export_settings, app.py) stays disabled until there
   is an optimized result to render — a smaller, previously-unchecked
   invariant folded in here per the same review finding.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

# Same anchoring rationale as the other test files: AppTest.from_file resolves
# a relative path against this file's directory, not the process cwd.
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


def test_jd_text_survives_a_profile_round_trip():
    """Type a JD, bounce Generator -> Profile -> Generator, and it must
    still be there — in both the durable session key and the redrawn
    widget. Writing session_state.jd_text directly here (instead of typing
    into the widget) would prove nothing: the widget's own `value=` would
    just overwrite it again on the very next render."""
    at = run_app(active_view="Generator")
    jd_key = f"jd_input_{at.session_state['base_editor_key']}"
    jd = "Seeking a senior widget engineer with 5+ years of Streamlit experience."

    at.text_area(key=jd_key).input(jd).run()
    assert not at.exception
    assert at.session_state["jd_text"] == jd

    at.sidebar.button(key="nav_Profile").click().run()
    assert at.session_state["active_view"] == "Profile"

    at.sidebar.button(key="nav_Generator").click().run()
    assert at.session_state["active_view"] == "Generator"
    assert at.session_state["jd_text"] == jd
    assert at.text_area(key=jd_key).value == jd


def test_custom_strategy_survives_a_profile_round_trip():
    """Same invariant, same mechanism, the second mirrored widget: editing
    the Custom Strategy box must survive the same round trip."""
    at = run_app(active_view="Generator")
    cp_key = f"cp_input_{at.session_state['base_editor_key']}"
    strategy = "Lead with quantified impact; keep every bullet under two lines."

    at.text_area(key=cp_key).input(strategy).run()
    assert not at.exception
    assert at.session_state["custom_prompt"] == strategy

    at.sidebar.button(key="nav_Profile").click().run()
    at.sidebar.button(key="nav_Generator").click().run()
    assert at.session_state["active_view"] == "Generator"
    assert at.session_state["custom_prompt"] == strategy
    assert at.text_area(key=cp_key).value == strategy


def test_generate_pdf_disabled_with_no_optimized_result():
    """A fresh session has nothing to render yet."""
    at = run_app(active_view="Generator")
    generate_buttons = [b for b in at.button if b.label == "Generate PDF"]
    assert len(generate_buttons) == 1
    assert generate_buttons[0].disabled is True
