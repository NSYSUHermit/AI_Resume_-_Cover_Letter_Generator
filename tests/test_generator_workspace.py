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
   the 25 pre-existing tests exercises it. The two tests below reproduce the
   original bug's exact trigger (a Generator -> Profile -> Generator round
   trip) and were confirmed, before being committed, to fail if the
   `st.session_state.jd_text = jd` mirror-back line is deleted.

   They do NOT independently cover hard-coding the widget key (dropping the
   base_editor_key suffix) — confirmed by testing that mutation directly:
   the round trip still passes, because every event that changes
   base_editor_key already fires an st.rerun() from outside
   render_generator_workspace() first, so the widget's cached value is
   cleared regardless of how the key is spelled. Full investigation in
   final-fix-report.md.

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


def test_custom_strategy_field_has_a_visible_micro_label():
    """Visual-polish pass, item 4: the reference design's own second named
    example ("CUSTOM STRATEGY", alongside "Job description") is a label
    rendered above the Custom Strategy field, not just the expander's own
    clickable header - so the field's label must actually be visible (it
    used to be label_visibility="collapsed" under the plainer text
    "Strategy", which the [data-testid="stWidgetLabel"] uppercase CSS rule
    would have had nothing to render). label_visibility.value == 0 is
    LabelVisibilityMessage's default ("visible") - the same value the JD
    field (never collapsed) also carries, checked here as a known-good
    reference point rather than a bare magic number."""
    at = run_app(active_view="Generator")
    cp_key = f"cp_input_{at.session_state['base_editor_key']}"
    jd_key = f"jd_input_{at.session_state['base_editor_key']}"
    strategy_field = at.text_area(key=cp_key)
    assert strategy_field.label == "Custom Strategy"
    assert strategy_field.proto.label_visibility.value == at.text_area(key=jd_key).proto.label_visibility.value


def test_optimize_resume_failure_adds_no_expanding_panel_and_stays_clickable(monkeypatch):
    """Item 4 (visual-match follow-up), owner's spec verbatim: 「optimizing
    resume 的動畫就跑在同一顆按鈕上就好不要額外延展」(the animation should just
    run on the same button, no extra expansion). ai.screen_job_description is
    patched to raise so ai_optimize_and_update() (app.py) returns a failure
    without ever calling st.rerun() - the same reason
    tests/test_ui_feedback.py's own end-to-end test exercises the failure
    path rather than success: a successful call reruns immediately, which
    AppTest follows to completion.

    This is the real app.py call site, not the isolated harness -
    tests/test_ui_feedback.py's new target-mode tests pin the actual
    on-the-button *content* (the .gp-btn-status line with the streamed
    milestone); AppTest only ever exposes the tree after a full script run
    completes, and this call site's own failure handling (app.py, next to
    the retry key) immediately redraws the real button into that same
    placeholder so the row stays clickable - so by the time this test's
    assertions run, that content has already been overwritten by the retry
    button, the same reason the walker itself is never directly observed in
    test_ui_feedback.py either (see that file's own comment on it). What
    *is* observable here, and is the actual regression this guards against:
    no st.status element exists anywhere in the tree (the old panel that
    used to open below the button), and the button's row is left clickable
    again rather than dead until some unrelated interaction reruns the
    page."""
    def boom(jd_text, api_key):
        raise RuntimeError("boom")
    monkeypatch.setattr("ai.screen_job_description", boom)

    at = run_app(active_view="Generator", api_key="fake-key", jd_text="A" * 60)
    optimize_buttons = [b for b in at.button if b.label == "Optimize Resume"]
    assert len(optimize_buttons) == 1
    optimize_buttons[0].click().run()

    assert not at.exception
    # No expanding panel: the old st.status(...) branch never ran.
    assert len(at.status) == 0
    assert any("Job description screening failed" in e.value for e in at.error)

    # The button's own row is clickable again, not stuck showing the frozen
    # failure line until some unrelated interaction reruns the page.
    retry_buttons = [b for b in at.button if b.label == "Optimize Resume"]
    assert len(retry_buttons) == 1
    assert retry_buttons[0].disabled is False
