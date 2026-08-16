"""Coverage for render_floating_progress() (app.py) - the pill-shaped bar
that replaced the vertical progress checklist in render_generator_panel().

workspace.application_progress() still owns the (label, done) logic and is
covered on its own in test_workspace.py; what's specific to this module is
the rendering contract: the bar only appears on the Generator view, and the
walker's horizontal position is the *highest-index completed stage*, not a
running count of how many are done (the two coincide in normal app usage,
since Generate PDF is disabled until a resume is optimized, but the render
code itself makes no such assumption - see the non-monotonic test below).
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


def progress_bar_markup(at):
    """The one markdown element that is the rendered bar itself.

    The stylesheet (injected on every run, every view) also contains the
    literal text "gp-floating-progress" as a bare CSS selector, so matching
    on that substring alone would find the <style> tag too. The rendered
    element carries the id="..." attribute; the CSS rule does not.
    """
    matches = [m for m in at.markdown if 'id="gp-floating-progress"' in m.value]
    return matches


def expected_stop_pct(index, total):
    """Mirrors render_floating_progress()'s own stop_pct(): evenly spaced
    stops across the track, expressed as a percentage so no pixel constant
    needs to be shared between Python and the stylesheet."""
    return round(index * 100 / (total - 1), 3) if total > 1 else 0.0


def test_generator_view_renders_bar_with_no_exception():
    at = run_app(active_view="Generator")
    assert not at.exception
    assert len(progress_bar_markup(at)) == 1


def test_walker_parks_at_first_stop_when_nothing_is_done():
    at = run_app(active_view="Generator")
    assert not at.exception
    markup = progress_bar_markup(at)[0].value
    assert f'gp-walker-wrap" style="left:{expected_stop_pct(0, 4)}%"' in markup
    assert 'aria-label="Application progress: Not started"' in markup


def test_walker_sits_at_last_completed_stage():
    """JD added + resume optimized = stages 0 and 1 done. The walker should
    rest on stop index 1 ("Resume optimized"), not stop 0."""
    at = run_app(active_view="Generator", jd_text="x" * 51, optimized_resume_data={})
    assert not at.exception
    stages = workspace.application_progress(
        jd_text="x" * 51, has_optimized=True, has_pdf=False, is_tracked=False
    )
    expected_index = 1
    assert [d for _, d in stages] == [True, True, False, False]

    markup = progress_bar_markup(at)[0].value
    expected_pct = expected_stop_pct(expected_index, len(stages))
    assert f'gp-walker-wrap" style="left:{expected_pct}%"' in markup
    assert "gp-stop-done" in markup
    assert markup.count("gp-stop-done") == 2
    assert "Resume optimized" in markup


def test_walker_uses_highest_completed_index_not_a_running_count():
    """Construct a state application.py's own UI would never reach on its
    own (tracker recorded without a generated PDF) specifically to prove the
    walker is driven by the highest-index done stage, not by counting Trues.
    A count-based implementation would misplace this at stop 1; the correct
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

    markup = progress_bar_markup(at)[0].value
    expected_pct = expected_stop_pct(3, len(stages))
    assert f'gp-walker-wrap" style="left:{expected_pct}%"' in markup
    assert "Saved to tracker" in markup


def test_walker_reaches_final_stop_when_all_stages_complete():
    at = run_app(
        active_view="Generator",
        jd_text="x" * 51,
        optimized_resume_data={},
        resume_preview_bytes=b"%PDF-1.4 fake",
        tracked_application_id="fake-id-123",
    )
    assert not at.exception
    markup = progress_bar_markup(at)[0].value
    assert 'gp-walker-wrap" style="left:100.0%"' in markup
    assert markup.count("gp-stop-done") == 4
    assert "All steps complete" in markup


def test_floating_progress_bar_absent_outside_generator_view():
    for view in ("Profile", "Tracker"):
        at = run_app(active_view=view)
        assert not at.exception
        assert progress_bar_markup(at) == []


def test_result_banner_and_progress_bar_coexist_without_exception():
    """render_result_banner() is called once, above the per-view dispatch, so
    a banner set while on Generator (e.g. right after Optimize Resume) can be
    showing at the very top of the Generator content at the same time as the
    bar - reproduce that ordering and confirm both still render cleanly.

    This cannot assert the two don't visually overlap (no browser in this
    harness); that's exactly why the bar's headroom lives on the shared
    stMainBlockContainer padding-top rule (applies before anything in the
    container, regardless of render order) rather than a spacer element
    emitted by render_floating_progress() itself - a spacer would only push
    down content that comes after it in the DOM, and the banner renders
    before it every time."""
    at = run_app(
        active_view="Generator",
        result_banner={"title": "Resume optimized", "details": ["2 roles"], "actions": []},
    )
    assert not at.exception
    assert len(progress_bar_markup(at)) == 1


def test_main_container_padding_covers_the_floating_bar():
    """Regression guard for the headroom computation: if this literal value
    drifts back toward the pre-bar 3.25rem, the bar (top:calc(3.75rem +
    0.75rem), roughly 4.3rem tall) would cover the top of Generator's content
    again. See the comment on this rule in app.py for the arithmetic."""
    at = run_app(active_view="Generator")
    style_matches = [m for m in at.markdown if "stMainBlockContainer" in m.value]
    assert len(style_matches) == 1
    assert "padding-top: 6.5rem;" in style_matches[0].value
