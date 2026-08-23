"""Coverage for the JSON paste boxes' discoverability and error reporting.

Two owner-reported problems, both about a user who ran the rewrite in an
external model and came back to paste the result:

1. Manual Result Import - the box built for exactly that - sat behind the
   sidebar's "Show advanced import tools" checkbox, so it was invisible
   unless you already knew to go looking for it. That checkbox is now gone
   entirely: all three boxes it gated (Manual Result Import, Manual Data
   Import, and the profile's own "Edit as JSON") render unconditionally,
   each in its own collapsed expander on the view it belongs to.

2. A syntax error in a pasted blob reported only Python's own
   "Invalid JSON: Expecting ',' delimiter: line 4 column 3 (char 88)",
   buried at the end of the message. json_error_report() (app.py) now leads
   with the line and column and quotes the offending line with a caret under
   it. The tests below assert on the line/column numbers and the caret block
   rather than on exact prose, so rewording the message does not break them.

AppTest anchoring follows the other test files: AppTest.from_file resolves a
relative path against this file's directory, not the process cwd.
"""
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


def paste_manual_result(at, raw):
    """Type `raw` into Manual Result Import and click Apply."""
    boxes = [t for t in at.text_area if t.key == "manual_ats_json"]
    assert len(boxes) == 1, "Manual Result Import box not found"
    boxes[0].input(raw).run()
    buttons = [b for b in at.button if b.label == "Apply Manual Result"]
    assert len(buttons) == 1
    buttons[0].click().run()
    return at


# ---------------------------------------------------------------------------
# Discoverability
# ---------------------------------------------------------------------------

def test_every_json_paste_box_is_visible_without_a_setting():
    """The whole point of the change: no checkbox required, anywhere. The
    sidebar's "Show advanced import tools" is gone, so all three boxes it
    used to gate render on their own view."""
    at = run_app(active_view="Generator")
    assert not at.exception
    assert [t for t in at.text_area if t.key == "manual_ats_json"], "Manual Result Import missing"
    assert [t for t in at.text_area if t.key == "manual_opt_input"], "Manual Data Import missing"

    # workspace.PROFILE - the sidebar labels it "Career Profile", the state
    # value is "Profile".
    at = run_app(active_view="Profile")
    assert not at.exception
    assert [t for t in at.text_area if t.key.startswith("base_json_import_")], \
        "the profile's Edit as JSON box should render without a setting"


def test_the_advanced_tools_checkbox_is_gone():
    """Nothing in the sidebar toggles those boxes any more - the checkbox was
    deleted, not just ignored."""
    at = run_app()
    assert not at.exception
    assert not [c for c in at.checkbox if c.label == "Show advanced import tools"]


def test_manual_result_import_still_applies_without_advanced_tools():
    """Visible is not enough - the un-gated box must still work end to end."""
    at = run_app(active_view="Generator")
    paste_manual_result(at, json.dumps({
        "optimized_resume": {"target_company": "Globex", "heading": {}, "skills": {}},
        "changelog": "Tightened the summary.",
    }))
    assert not at.exception
    assert at.session_state["optimized_resume_data"]["target_company"] == "Globex"
    assert at.session_state["changelog"] == "Tightened the summary."


# ---------------------------------------------------------------------------
# Error reporting
# ---------------------------------------------------------------------------

def test_invalid_json_error_names_the_line_and_column():
    # Missing comma after the "target_company" line -> the parser trips on
    # line 4, where it wanted a delimiter.
    broken = '{\n  "optimized_resume": {\n    "target_company": "Globex"\n    "target_role": "SWE"\n  }\n}'
    at = run_app(active_view="Generator")
    paste_manual_result(at, broken)

    assert not at.exception
    assert len(at.error) == 1
    message = at.error[0].value
    assert "line 4" in message
    assert "column" in message
    # The offending line is quoted back, with a caret under the column.
    assert '"target_role"' in message
    assert "^" in message


def test_invalid_json_error_quotes_a_single_line_paste():
    """json.dumps() without indent - the common shape of a blob copied out
    of another tool - is all one line, so the snippet is windowed around the
    error column rather than dumped whole."""
    long_blob = json.dumps({"optimized_resume": {"summary": "x" * 400}})[:-1]  # drop the closing brace
    at = run_app(active_view="Generator")
    paste_manual_result(at, long_blob)

    assert not at.exception
    assert len(at.error) == 1
    message = at.error[0].value
    assert "line 1" in message
    assert "^" in message
    # Windowed, not the whole 400-char line.
    assert "x" * 400 not in message


def test_wrapper_key_missing_error_lists_the_keys_it_found():
    """Pasting the resume object itself (no "optimized_resume" wrapper) is
    the most likely mistake here, so the error names the keys that ARE
    present and points at the box that accepts that shape."""
    at = run_app(active_view="Generator")
    paste_manual_result(at, json.dumps({"heading": {}, "experience": [], "skills": {}}))

    assert not at.exception
    assert len(at.error) == 1
    message = at.error[0].value
    assert "optimized_resume" in message
    assert "heading" in message
    assert "Manual Data Import" in message
    # Nothing was imported.
    assert not at.session_state["optimized_resume_data"]


def test_non_object_json_is_rejected_without_crashing():
    """json.loads("[1, 2]") parses fine but has no .get() - the isinstance
    guard is what keeps that from raising inside the import branch."""
    at = run_app(active_view="Generator")
    paste_manual_result(at, "[1, 2]")

    assert not at.exception
    assert len(at.error) == 1
    assert "optimized_resume" in at.error[0].value
