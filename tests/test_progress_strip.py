"""Coverage for render_progress_strip() (app.py) - the thin, full-width
status strip pinned to the top of the Generator view.

Replaces the older floating pill-shaped bar (render_floating_progress(),
#gp-floating-progress, formerly covered by tests/test_floating_progress.py)
that the owner said read as a fat, centred pill rather than something
"thin" - this version is a hairline fill track plus small inline labels,
with no walking figure (see the #gp-status-strip comment in app.py's
stylesheet block for why the figure was dropped instead of shrunk to fit;
theme.walker_svg() is unchanged and still used by ui_feedback.run_ai_call(),
covered separately in test_ui_feedback.py).

workspace.application_progress() still owns the (label, done) logic and is
covered on its own in test_workspace.py; what's specific to this module is
the rendering contract: the strip only appears on the Generator view, and
the fill bar's width (and which stop dots read as "done") track the
*highest-index completed stage*, not a running count of how many are done
(the two coincide in normal app usage, since Generate PDF is disabled until
a resume is optimized, but the render code itself makes no such assumption -
see the non-monotonic test below, carried over unchanged from the pill's own
coverage).
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

import workspace

# Same anchoring rationale as the other test files: AppTest.from_file resolves
# a relative path against this file's directory, not the process cwd.
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


def progress_strip_markup(at):
    """The one markdown element that is the rendered strip itself.

    The stylesheet (injected on every run, every view) also contains the
    literal text "gp-status-strip" as a bare CSS selector, so matching on
    that substring alone would find the <style> tag too. The rendered
    element carries the id="..." attribute; the CSS rule does not.
    """
    matches = [m for m in at.markdown if 'id="gp-status-strip"' in m.value]
    return matches


def expected_stop_pct(index, total):
    """Mirrors render_progress_strip()'s own stop_pct(): evenly spaced stops
    across the track, expressed as a percentage so no pixel constant needs to
    be shared between Python and the stylesheet. The fill bar's own width
    uses this same helper, evaluated at the highest-index completed stage."""
    return round(index * 100 / (total - 1), 3) if total > 1 else 0.0


def test_generator_view_renders_strip_with_no_exception():
    at = run_app(active_view="Generator")
    assert not at.exception
    assert len(progress_strip_markup(at)) == 1


def test_strip_fill_sits_at_zero_when_nothing_is_done():
    at = run_app(active_view="Generator")
    assert not at.exception
    markup = progress_strip_markup(at)[0].value
    assert f'gp-strip-fill" style="width:{expected_stop_pct(0, 4)}%"' in markup
    assert 'aria-label="Application progress: Not started"' in markup
    assert "gp-strip-stop-done" not in markup


def test_fill_sits_at_last_completed_stage():
    """JD added + resume optimized = stages 0 and 1 done. The fill (and the
    label) should reflect stop index 1 ("Resume optimized"), not stop 0."""
    at = run_app(active_view="Generator", jd_text="x" * 51, optimized_resume_data={})
    assert not at.exception
    stages = workspace.application_progress(
        jd_text="x" * 51, has_optimized=True, has_pdf=False, is_tracked=False
    )
    expected_index = 1
    assert [d for _, d in stages] == [True, True, False, False]

    markup = progress_strip_markup(at)[0].value
    expected_pct = expected_stop_pct(expected_index, len(stages))
    assert f'gp-strip-fill" style="width:{expected_pct}%"' in markup
    assert markup.count("gp-strip-stop-done") == 2
    assert "Resume optimized" in markup


def test_fill_uses_highest_completed_index_not_a_running_count():
    """Construct a state application.py's own UI would never reach on its
    own (tracker recorded without a generated PDF) specifically to prove the
    fill is driven by the highest-index done stage, not by counting Trues. A
    count-based implementation would misplace this at stop 1; the correct
    "last completed stage" reading is stop 3."""
    at = run_app(
        active_view="Generator",
        jd_text="x" * 51,
        tracked_application_id="fake-id-123",
    )
    assert not at.exception
    stages = workspace.application_progress(
        jd_text="x" * 51, has_optimized=False, has_pdf=False, is_tracked=True
    )
    assert [d for _, d in stages] == [True, False, False, True]

    markup = progress_strip_markup(at)[0].value
    expected_pct = expected_stop_pct(3, len(stages))
    assert f'gp-strip-fill" style="width:{expected_pct}%"' in markup
    assert "Saved to tracker" in markup


def test_fill_reaches_full_when_all_stages_complete():
    at = run_app(
        active_view="Generator",
        jd_text="x" * 51,
        optimized_resume_data={},
        resume_preview_bytes=b"%PDF-1.4 fake",
        tracked_application_id="fake-id-123",
    )
    assert not at.exception
    markup = progress_strip_markup(at)[0].value
    assert 'gp-strip-fill" style="width:100.0%"' in markup
    assert markup.count("gp-strip-stop-done") == 4
    assert "All steps complete" in markup


def test_status_strip_absent_outside_generator_view():
    for view in ("Profile", "Tracker"):
        at = run_app(active_view=view)
        assert not at.exception
        assert progress_strip_markup(at) == []


def test_result_banner_and_status_strip_coexist_without_exception():
    """render_result_banner() is called once, above the per-view dispatch, so
    a banner set while on Generator (e.g. right after Optimize Resume) can be
    showing at the very top of the Generator content at the same time as the
    strip - reproduce that ordering and confirm both still render cleanly.

    This is also the exact state that used to defeat render_generator_
    splitter()'s own column lookup before it was anchored on the
    gp_workspace_col/gp_preview_col markers (see that function's own
    docstring, and tests/test_generator_splitter.py) - the banner's
    st.columns([20, 1]) row and this strip both existing on Generator at
    once is not a corner case, it is what the screen looks like immediately
    after every successful Optimize Resume.

    This cannot assert the two don't visually overlap (no browser in this
    harness); that's exactly why the strip's headroom lives on the shared
    stMainBlockContainer padding-top rule (applies before anything in the
    container, regardless of render order) rather than a spacer element
    emitted by render_progress_strip() itself - a spacer would only push
    down content that comes after it in the DOM, and the banner renders
    before it every time."""
    at = run_app(
        active_view="Generator",
        result_banner={"title": "Resume optimized", "details": ["2 roles"], "actions": []},
    )
    assert not at.exception
    assert len(progress_strip_markup(at)) == 1


def test_main_container_padding_is_pinned():
    """Pinned-value drift guard for the Generator top-padding literal - NOT a
    coverage proof. This harness has no browser, so it can only confirm the
    number in the stylesheet has not silently drifted back toward something
    too small to clear the strip (e.g. the pre-strip 3.25rem, or the 9.5rem
    the old floating pill needed - this strip is deliberately much thinner,
    so it needs much less); it cannot confirm the strip and the content
    below it actually stay clear of each other on screen - that would need a
    real browser. See the comment on the stMainBlockContainer rule in app.py
    for the arithmetic behind this specific number."""
    at = run_app(active_view="Generator")
    style_matches = [m for m in at.markdown if "stMainBlockContainer" in m.value]
    assert len(style_matches) == 1
    assert "padding-top: 5.75rem;" in style_matches[0].value


def test_main_container_padding_is_smaller_outside_generator():
    """Career Profile and Tracker never render the status strip
    (test_status_strip_absent_outside_generator_view, above), so unlike
    Generator neither needs the headroom that clears it."""
    for view in ("Profile", "Tracker"):
        at = run_app(active_view=view)
        style_matches = [m for m in at.markdown if "stMainBlockContainer" in m.value]
        assert len(style_matches) == 1
        assert "padding-top: 3.25rem;" in style_matches[0].value
        assert "padding-top: 5.75rem;" not in style_matches[0].value
