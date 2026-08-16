"""Coverage for UI Task 4's restyle of ui_feedback.run_ai_call(): same real
milestone messages, compact single-line panel with the Task 1 walker marching
beside the current one, instead of an append-only list of every message seen
so far. The design doc is explicit that the message *content* must not
degrade to a decorative animation ("生成過程保留真實里程碑，只換視覺") - these
tests check that the content survives exactly, and that the "compact" /
"current line only" claim is real (not still an accumulating log with extra
CSS on top).

Most tests here use AppTest.from_string() with a tiny script that imports
run_ai_call directly, rather than booting the full app.py: run_ai_call has no
page-level side effects of its own (unlike app.py, which is a top-level
script - see tests/test_generator_preview.py's module docstring on why that
file can't be dotted-path-monkeypatched), so a minimal harness is enough and
keeps these tests independent of Generator-specific setup. One test at the
bottom goes through the real app.py call site (render_api_key_setup) to
confirm the wiring holds end-to-end, not just in isolation.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"

RUN_AI_CALL_HARNESS = """
import streamlit as st
from ui_feedback import run_ai_call

def fn(report):
    for message in MESSAGES:
        report(message)
    return RESULT

# Mirrors every real call site (app.py, firebase_dashboard.py): fn() itself
# returns whatever shape success= expects to inspect - run_ai_call() returns
# that value unchanged, it does not unpack anything on the caller's behalf.
result = run_ai_call(LABEL, lambda report: fn(report), success=lambda r: OK)
st.session_state["returned"] = result
"""


def run_harness(messages, label="Doing a thing", result="the-result", ok=True):
    """Build and run the tiny harness script above."""
    src = (
        f"MESSAGES = {messages!r}\n"
        f"LABEL = {label!r}\n"
        f"RESULT = {result!r}\n"
        f"OK = {ok!r}\n"
    ) + RUN_AI_CALL_HARNESS
    at = AppTest.from_string(src)
    at.run()
    return at


def status_markdown(at):
    assert len(at.status) == 1
    return [m.value for m in at.status[0].markdown]


# Item 4 (visual-match follow-up), owner: 「optimizing resume 的動畫就跑在同一顆
# 按鈕上就好不要額外延展」. `target=` renders into an already-existing placeholder
# instead of opening the st.status panel above - see run_ai_call()'s own
# docstring for the full rationale. Same minimal-harness approach as
# RUN_AI_CALL_HARNESS above, just handing it a plain st.empty() placeholder
# rather than letting it build its own st.status. This intentionally does NOT
# simulate the real call site's "redraw the button into the placeholder on
# failure" step (app.py) - that step overwrites the very content these tests
# check, which is exactly why tests/test_generator_workspace.py's end-to-end
# test cannot observe it either and instead only checks that no panel was
# ever created. This harness is what actually pins the on-the-button content.
TARGET_HARNESS = """
import streamlit as st
from ui_feedback import run_ai_call

def fn(report):
    for message in MESSAGES:
        report(message)
    return RESULT

slot = st.empty()
result = run_ai_call(LABEL, lambda report: fn(report), success=lambda r: OK, target=slot)
st.session_state["returned"] = result
"""


def run_target_harness(messages, label="Doing a thing", result="the-result", ok=True):
    src = (
        f"MESSAGES = {messages!r}\n"
        f"LABEL = {label!r}\n"
        f"RESULT = {result!r}\n"
        f"OK = {ok!r}\n"
    ) + TARGET_HARNESS
    at = AppTest.from_string(src)
    at.run()
    return at


def target_markdown(at):
    """The .gp-btn-status line(s) rendered into the target placeholder - not
    at.status[0].markdown, since target= mode never creates an st.status at
    all (that is the entire point being tested)."""
    return [m.value for m in at.markdown if '<div class="gp-btn-status">' in m.value]


def test_target_mode_renders_on_the_placeholder_not_a_status_panel():
    at = run_target_harness(["first stage", "second stage"])
    assert not at.exception
    assert len(at.status) == 0
    lines = target_markdown(at)
    assert len(lines) == 1
    assert "second stage" in lines[0]
    assert "first stage" not in lines[0]


def test_target_mode_shows_the_label_immediately_before_any_report_call():
    """Unlike the panel path (whose st.status(label, ...) header already
    carries the label the instant it is created), a placeholder starts out
    holding whatever the caller last drew into it - so target mode explicitly
    draws `label` in first, before fn() runs, so the row reads as busy from
    the first instant rather than sitting blank until the first report()."""
    at = run_target_harness([], label="Optimizing resume", result="r", ok=True)
    assert not at.exception
    lines = target_markdown(at)
    assert len(lines) == 1
    assert "Optimizing resume" in lines[0]


def test_target_mode_escapes_html_same_as_the_panel_path():
    message = 'R&D Lead <script>alert(1)</script> "Special" Corp'
    at = run_target_harness([message])
    assert not at.exception
    lines = target_markdown(at)
    assert "<script>" not in lines[0]
    assert "&amp;D Lead" in lines[0]
    assert "&lt;script&gt;" in lines[0]


def test_target_mode_freezes_the_last_line_without_the_walker_on_success():
    at = run_target_harness(["in progress..."], result="ok", ok=True)
    assert not at.exception
    lines = target_markdown(at)
    assert len(lines) == 1
    assert "<svg" not in lines[0]
    assert "in progress..." in lines[0]
    assert at.session_state["returned"] == "ok"


def test_target_mode_keeps_the_frozen_message_on_failure():
    at = run_target_harness(["about to fail"], result="boom", ok=False)
    assert not at.exception
    lines = target_markdown(at)
    assert len(lines) == 1
    assert "<svg" not in lines[0]
    assert "about to fail" in lines[0]


def test_only_the_latest_message_is_shown_not_a_growing_log():
    """Design doc: "面板改為緊湊樣式...右側是最新的里程碑文字" (the latest
    milestone text) - singular, not a running history. Three report() calls
    must leave exactly one status-line element behind, holding only the
    third message."""
    at = run_harness(["first stage", "second stage", "third stage"])
    assert not at.exception
    lines = status_markdown(at)
    assert len(lines) == 1
    assert "third stage" in lines[0]
    assert "first stage" not in lines[0]
    assert "second stage" not in lines[0]


def test_message_content_is_preserved_verbatim():
    """"Keep every message exactly as-is" (task spec) at the content level -
    special characters and punctuation a real report() call uses elsewhere in
    this app (em dash, percent signs, arrows) must not be mangled."""
    message = "Coverage 42% → 81% — 3 new keywords"
    at = run_harness([message])
    assert not at.exception
    lines = status_markdown(at)
    assert message in lines[0]


def test_html_special_characters_in_a_message_are_escaped_not_interpreted():
    """report() messages can carry AI-echoed job-description text -
    ai_optimize_and_update()'s "Target: ..." line (app.py) includes the
    screening model's target_company/target_role, both read out of whatever
    JD the user pasted in. This now renders via unsafe_allow_html=True (the
    old st.write(message) ran everything through markdown's own escaping
    instead), so a literal "<"/"&" in a company name must not be interpreted
    as markup - only the walker/div wrapper this module itself controls is
    unescaped HTML; the message is not."""
    message = 'R&D Lead <script>alert(1)</script> "Special" Corp'
    at = run_harness([message])
    assert not at.exception
    lines = status_markdown(at)
    assert "<script>" not in lines[0]
    assert "&amp;D Lead" in lines[0]
    assert "&lt;script&gt;" in lines[0]


def test_success_freezes_the_last_line_without_the_walker():
    """The walker marches only while the call is genuinely in flight; once
    fn() has returned, the line is redrawn without it (ui_feedback.py's own
    docstring: a failed call has no rerun to tear the panel down, so a
    perpetually marching figure next to a resolved message would misreport
    "still working"). Success normally vanishes behind the caller's own
    st.rerun() almost immediately, but the frozen state is still what this
    function itself leaves behind the instant fn() returns, which is what
    this test observes."""
    at = run_harness(["in progress..."], result="ok", ok=True)
    assert not at.exception
    lines = status_markdown(at)
    assert len(lines) == 1
    assert "<svg" not in lines[0]
    assert "in progress..." in lines[0]
    assert at.status[0].label == "Doing a thing — done"
    assert at.status[0].state == "complete"
    assert at.session_state["returned"] == "ok"


def test_failure_keeps_panel_open_with_frozen_last_message():
    at = run_harness(["about to fail"], result="boom", ok=False)
    assert not at.exception
    lines = status_markdown(at)
    assert len(lines) == 1
    assert "<svg" not in lines[0]
    assert "about to fail" in lines[0]
    assert at.status[0].label == "Doing a thing — failed"
    assert at.status[0].state == "error"


def test_zero_report_calls_does_not_raise():
    """fn() is allowed to fail before ever calling report() once (e.g. a
    missing API key checked before the first real stage) - the freeze step
    must not choke on "no message was ever shown"."""
    at = run_harness([], result="boom", ok=False)
    assert not at.exception
    assert at.status[0].state == "error"


def test_multi_stage_call_runs_cleanly_end_to_end():
    """General robustness: several report() calls in sequence (matching
    ai_optimize_and_update()'s five real stages in app.py) must not raise,
    beyond the single/double-message cases the tests above already cover."""
    at = run_harness(["one", "two", "three", "four", "five"])
    assert not at.exception
    assert "five" in status_markdown(at)[0]


def test_walker_svg_markup_is_well_formed():
    """The asset contract run_ai_call() renders from. This cannot prove the
    walker is ever actually painted mid-call in a real browser - AppTest only
    exposes the tree after a full script run completes, by which point
    run_ai_call()'s own freeze step (tested above) has already replaced it -
    so this only checks that theme.walker_svg() itself produces the expected
    shape. run_ai_call() is this function's only remaining caller (app.py's
    top status strip, render_progress_strip(), does not use it - see that
    function's own docstring), but the shape contract is still worth pinning
    on its own terms rather than only implicitly through the panel tests
    above."""
    import theme
    markup = theme.walker_svg()
    assert '<svg class="gp-walker"' in markup
    assert 'class="gp-legs"' in markup and 'class="gp-legs2"' in markup


def test_api_key_check_failure_goes_through_the_real_app_call_site(monkeypatch):
    """End-to-end through the real render_api_key_setup() -> run_ai_call()
    call site in app.py, not the isolated harness above - confirms theme.py /
    ui_feedback.py / app.py's stylesheet actually wire together. The failure
    path (not success) is used deliberately: a successful key check calls
    st.rerun() immediately (app.py), which AppTest follows to completion, so
    render_api_key_setup() would no longer even be on screen by the time the
    assertions run; failure leaves the panel in place (st.error(msg) instead
    of a rerun), which is what makes it observable here."""
    monkeypatch.setattr("ai.test_api_key", lambda api_key: (False, "Invalid key."))

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    key_inputs = [t for t in at.text_input if t.key == "api_key_input"]
    assert len(key_inputs) == 1
    key_inputs[0].input("fake-key-value").run()

    save_buttons = [b for b in at.button if b.label == "Save and test key"]
    assert len(save_buttons) == 1
    save_buttons[0].click().run()

    assert not at.exception
    assert len(at.status) == 1
    assert at.status[0].label == "Checking your key — failed"
    assert at.status[0].state == "error"
    lines = [m.value for m in at.status[0].markdown]
    assert len(lines) == 1
    assert "Sending a test request to Gemini..." in lines[0]
    assert "<svg" not in lines[0]
    assert any("Invalid key." in e.value for e in at.error)
