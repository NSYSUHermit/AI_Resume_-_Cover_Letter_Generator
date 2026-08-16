"""Coverage for render_generator_splitter() (app.py) - the draggable resize
handle between the Generator view's two columns - and for the removal of the
`Panel width` st.segmented_control / PANEL_RATIOS workaround it replaces.

What AppTest can and cannot prove about a components.html()-injected script
is asymmetric, and deliberately kept that way here rather than papered over.
AppTest exposes the *emitted HTML string* for an st.components.v1.html()
call (confirmed empirically: it surfaces as an UnknownElement with
type=="iframe" and a real .srcdoc string - there is no dedicated Iframe
wrapper class in streamlit.testing.v1.element_tree, so `at.get("iframe")`
is used directly rather than a typed accessor like `at.button`). It never
boots a browser, never parses the iframe's DOM, and never dispatches a
pointer event. So this file can prove the script is emitted only where it
should be, that it is syntactically valid JavaScript, and that the specific
guards the task's own brief called out are present in the source text. It
cannot prove the handle finds the right columns in a real DOM, drags
smoothly, clamps visually on screen, or survives a real page reload - that
needs a human with a browser (see render_generator_splitter()'s own
"UNVERIFIED" docstring section, and report.md).
"""
import shutil
import subprocess
from pathlib import Path

import pytest
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


def splitter_iframes(at):
    """Every st.components.v1.html() call renders as an "iframe"-typed
    element in AppTest's tree - app.py has up to three on Generator (the PDF
    previewer, the Copy Prompt button, and this handle) - so filter by the
    one string unique to the splitter's own injected script (its
    localStorage key) rather than assuming list position or count."""
    return [f for f in at.get("iframe") if "gp-splitter-left-pct" in f.srcdoc]


def splitter_script(at):
    matches = splitter_iframes(at)
    assert len(matches) == 1
    html = matches[0].srcdoc
    start = html.index("<script>") + len("<script>")
    end = html.index("</script>")
    return html[start:end]


# ---------------------------------------------------------------------------
# The `Panel width` workaround is gone
# ---------------------------------------------------------------------------


def test_panel_width_control_is_gone():
    """The owner rejected the three-preset st.segmented_control substitute
    explicitly, twice. Nothing with that label, and nothing keyed
    "panel_ratio_control", may exist anywhere in the app."""
    at = run_app(active_view="Generator")
    assert not at.exception
    assert not any(sc.label == "Panel width" for sc in at.segmented_control)
    assert [sc for sc in at.segmented_control if sc.key == "panel_ratio_control"] == []


def test_panel_ratio_not_in_session_state():
    at = run_app(active_view="Generator")
    assert not at.exception
    assert "panel_ratio" not in at.session_state


def test_panel_ratio_removed_from_source_as_code_not_just_at_runtime():
    """The two tests above only prove the widget never renders and the
    session key never gets set - not that PANEL_RATIOS and its control
    function were deleted outright rather than merely orphaned. Checks
    lowercase `panel_ratio` specifically (how it would appear as a
    session-state key, a widget `key=`, or a variable/function name) rather
    than banning every mention of the removed feature outright:
    render_generator_splitter()'s own docstring legitimately still says
    "PANEL_RATIOS, removed along with this" (uppercase, case-sensitively
    distinct from the check below) as historical context for why the
    splitter exists - this file explains most of its own past decisions in
    comments the same way, and that one is exactly the kind the task asked
    this docstring to carry."""
    source = APP_PATH.read_text()
    assert "panel_ratio" not in source
    assert "def render_panel_ratio_control" not in source


# ---------------------------------------------------------------------------
# The splitter script itself
# ---------------------------------------------------------------------------


def test_splitter_emitted_on_generator_only():
    for view, expected_count in (("Profile", 0), ("Generator", 1), ("Tracker", 0)):
        at = run_app(active_view=view)
        assert not at.exception
        assert len(splitter_iframes(at)) == expected_count, view


def test_splitter_still_emitted_when_generator_shows_a_result_banner():
    """Regression guard for the exact state that used to defeat the column
    lookup before it was anchored on the gp_workspace_col/gp_preview_col
    markers (see render_generator_splitter()'s own docstring): a result
    banner showing at the top of Generator - an ordinary state, e.g.
    immediately after a successful Optimize Resume - used to be mistaken for
    the split itself. This does not (cannot, via AppTest) prove the handle
    now attaches to the *correct* row instead; it only proves the script is
    still emitted (not silently dropped) when a banner is present."""
    at = run_app(
        active_view="Generator",
        result_banner={"title": "Resume optimized", "details": ["2 roles"], "actions": []},
    )
    assert not at.exception
    assert len(splitter_iframes(at)) == 1


def test_splitter_script_uses_pointer_events_not_legacy_mouse_events():
    """Checks actual addEventListener(...) registrations, not bare substring
    presence: the script's own comment explaining this choice ("pointerdown/
    pointermove/pointercapture, not mousedown/mousemove: ...") legitimately
    contains the literal text "mousedown"/"mousemove" as prose, which a bare
    `"mousedown" not in js` would trip on."""
    at = run_app(active_view="Generator")
    js = splitter_script(at)
    for evt in ("pointerdown", "pointermove", "pointerup", "pointercancel"):
        assert f'addEventListener("{evt}"' in js, evt
    assert "setPointerCapture" in js
    assert "releasePointerCapture" in js
    for legacy in ("mousedown", "mousemove", "mouseup"):
        assert f'addEventListener("{legacy}"' not in js, legacy
        assert f"on{legacy}" not in js, legacy


def test_splitter_script_clamps_to_25_75():
    at = run_app(active_view="Generator")
    js = splitter_script(at)
    assert "MIN_PCT = 25" in js
    assert "MAX_PCT = 75" in js
    assert "clamp(" in js


def test_splitter_script_persists_the_ratio_to_local_storage():
    at = run_app(active_view="Generator")
    js = splitter_script(at)
    assert "localStorage" in js
    assert "gp-splitter-left-pct" in js


def test_splitter_script_self_heals_via_mutation_observer():
    """"must be idempotent and must survive Streamlit re-rendering the
    block" - the re-attach mechanism the task brief specifically asks for."""
    at = run_app(active_view="Generator")
    js = splitter_script(at)
    assert "MutationObserver" in js
    assert "childList" in js
    # Idempotent: must check for an existing handle before making a new one.
    assert "gp-split-handle" in js


def test_splitter_script_guards_every_top_level_lookup():
    """"Guard every DOM lookup ... A JS exception must never break the
    page": the script's entry points (ensure(), and the observer/
    localStorage setup around it) must each sit inside their own try/catch
    rather than trusting the caller."""
    at = run_app(active_view="Generator")
    js = splitter_script(at)
    assert js.count("try {") >= 3
    assert (js.count("catch (e)") + js.count("catch (err)")) >= 3
    assert "return null" in js  # findSplit()'s guarded-lookup exits


def test_splitter_script_anchors_on_data_testid_and_own_markers_only():
    """Constraint from the task brief: anchor on data-testid attributes
    only, never on a st-emotion-cache-* hash.

    The two non-data-testid selectors are `[data-gp-col="workspace"]` and
    `[data-gp-col="preview"]` - attributes this app emits itself, so they
    cannot be broken by a Streamlit class rename.

    These used to be `.st-key-gp_workspace_col` / `.st-key-gp_preview_col`,
    produced by `st.container(key=...)`. That was wrong in a way no test
    here caught: Streamlit emits no DOM node at all for a container with
    nothing inside it, so the classes were absent from the live document and
    findSplit() silently returned null on every render. Verified in a real
    browser, not inferred. See test_column_markers_are_actually_emitted for
    the assertion that now closes that gap.

    The st-emotion-cache check asserts the hash is absent as a *selector*
    rather than as a substring - the script's own comment legitimately names
    it once, in prose, to say that is exactly what it is not anchored on."""
    at = run_app(active_view="Generator")
    js = splitter_script(at)
    assert "data-testid" in js
    assert "stMainBlockContainer" in js
    assert "stHorizontalBlock" in js
    assert "stColumn" in js
    assert '[data-gp-col="workspace"]' in js
    assert '[data-gp-col="preview"]' in js
    assert ".st-emotion-cache" not in js


def test_column_markers_are_actually_emitted():
    """The markers the splitter and the two-tone background both depend on
    must exist as real elements in the rendered output.

    This is the test whose absence let an empty `st.container(key=...)` ship
    as an anchor for two features while emitting no DOM node whatsoever.
    Asserting the selector appears in the injected script is not enough -
    something has to check the thing being selected actually renders."""
    at = run_app(active_view="Generator")
    emitted = " ".join(h.body for h in at.get("html"))
    assert 'data-gp-col="workspace"' in emitted
    assert 'data-gp-col="preview"' in emitted


def test_column_markers_absent_outside_generator():
    """No markers on the other views, so the background rule and the handle
    cannot latch onto Profile's or Tracker's layout."""
    for view in ("Profile", "Tracker"):
        at = run_app(active_view=view)
        emitted = " ".join(h.body for h in at.get("html"))
        assert "data-gp-col" not in emitted, view


def test_splitter_script_is_syntactically_valid_javascript():
    """The one check here that goes beyond "grep the source": actually
    parses the emitted script with a real JS engine (`node --check`, which
    parses without executing). Skipped, not failed, if this machine has no
    `node` on PATH - this Python project does not depend on Node.js
    (neither requirements.txt nor requirements-dev.txt mention it), so a
    deploy or CI environment is not guaranteed to have it either. Where it
    is available, this is a real syntax proof, not a structural guess - see
    report.md for the run that confirmed it here."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available on PATH")

    at = run_app(active_view="Generator")
    js = splitter_script(at)
    result = subprocess.run(
        [node, "--check", "/dev/stdin"],
        input=js,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_splitter_not_present_on_profile_or_tracker_even_with_generator_state_set():
    """Belt-and-braces on top of test_splitter_emitted_on_generator_only:
    stale Generator-shaped session state (e.g. left over from a previous
    view) must not leak the handle onto Profile/Tracker - the guard is
    render_generator_splitter()'s call site (only reached inside `if
    active_view == workspace.GENERATOR:`), not anything about the state
    itself."""
    for view in ("Profile", "Tracker"):
        at = run_app(
            active_view=view,
            jd_text="x" * 51,
            optimized_resume_data={"target_company": "Acme"},
            resume_preview_bytes=b"%PDF-1.4 fake",
        )
        assert not at.exception
        assert splitter_iframes(at) == []


def test_splitter_cleanup_runs_off_generator():
    """Leaving Generator must actively remove the handle.

    The handle is inserted into window.parent.document, so it outlives the
    component iframe that created it - navigating away tore down the iframe
    but left the bar painted across Profile and Tracker. Nothing inside a
    removed iframe can clean up after itself, so removal is driven from
    whichever view is rendering instead.
    """
    for view in ("Profile", "Tracker"):
        at = run_app(active_view=view)
        emitted = " ".join(f.srcdoc for f in at.get("iframe"))
        assert "gp-split-handle" in emitted, view          # the cleanup script
        assert "removeChild" in emitted, view
        assert "pointerdown" not in emitted, view          # but not the injector
