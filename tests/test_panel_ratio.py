"""Coverage for UI Task 4's panel-ratio control: render_panel_ratio_control()
and PANEL_RATIOS (app.py) - the user-approved substitute for a draggable
splitter between the Generator view's two columns (design doc "需求 8 的裁決：
分段控制取代拖曳"). A st.segmented_control offering three named presets, top of
the Generator view, feeding st.columns(...)'s ratio directly.

On the durable-key pattern: the control's own widget key
("panel_ratio_control") is dropped by Streamlit on any rerun where the
control is not drawn - the same mechanism documented and regression-tested
for the JD text area in tests/test_generator_workspace.py. panel_ratio (a
plain session_state key, mirrored from the widget's value on every render) is
what actually needs to survive a trip away from Generator.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

# Same anchoring rationale as the other test files: AppTest.from_file resolves
# a relative path against this file's directory, not the process cwd.
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"

# Mirrors app.py's own PANEL_RATIOS. app.py cannot be imported normally to
# pull the real dict in (see tests/test_generator_preview.py's module
# docstring: AppTest.from_file() executes it fresh, every run, as "__main__",
# not as a module registered under "app" in sys.modules) - every other test
# file in this suite that needs to check an app.py-owned constant against
# expected behaviour mirrors it the same way (e.g.
# test_floating_progress.py's expected_stop_pct()).
PANEL_RATIO_PRESETS = ["Wide preview", "Even", "Wide workspace"]


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


def ratio_control(at):
    """The panel-ratio segmented_control, found by its own widget key
    ("panel_ratio_control") rather than by list position - render_preview()
    (app.py) has its own st.segmented_control (the Resume/Cover Letter
    switch, key "tr") on the same view."""
    matches = [sc for sc in at.segmented_control if sc.key == "panel_ratio_control"]
    assert len(matches) == 1
    return matches[0]


def test_panel_ratio_control_present_with_three_presets_on_generator():
    at = run_app(active_view="Generator")
    assert not at.exception
    control = ratio_control(at)
    assert control.options == PANEL_RATIO_PRESETS


def test_panel_ratio_defaults_to_even():
    """Design doc: "預設 Even"."""
    at = run_app(active_view="Generator")
    assert not at.exception
    assert at.session_state["panel_ratio"] == "Even"
    assert ratio_control(at).value == "Even"


def test_panel_ratio_control_absent_outside_generator():
    for view in ("Profile", "Tracker"):
        at = run_app(active_view=view)
        assert not at.exception
        assert [sc for sc in at.segmented_control if sc.key == "panel_ratio_control"] == []


def test_switching_ratio_control_updates_session_state():
    at = run_app(active_view="Generator")
    ratio_control(at).set_value("Wide workspace").run()
    assert not at.exception
    assert at.session_state["panel_ratio"] == "Wide workspace"


def test_panel_ratio_choice_survives_a_profile_round_trip():
    """Same round-trip shape as test_generator_workspace.py's JD coverage:
    pick a non-default preset, bounce Generator -> Profile -> Generator, and
    both the durable session key and the redrawn widget must still reflect
    the choice - not silently reset to "Even" because the widget's own key
    was dropped while Profile was on screen."""
    at = run_app(active_view="Generator")
    ratio_control(at).set_value("Wide preview").run()
    assert at.session_state["panel_ratio"] == "Wide preview"

    at.sidebar.button(key="nav_Profile").click().run()
    assert at.session_state["active_view"] == "Profile"
    assert at.session_state["panel_ratio"] == "Wide preview"
    # The widget itself does not exist while on Profile.
    assert [sc for sc in at.segmented_control if sc.key == "panel_ratio_control"] == []

    at.sidebar.button(key="nav_Generator").click().run()
    assert at.session_state["active_view"] == "Generator"
    assert at.session_state["panel_ratio"] == "Wide preview"
    assert ratio_control(at).value == "Wide preview"


def test_generator_renders_without_exception_under_each_preset():
    """Structural smoke test for all three presets - deliberately does not
    (cannot, via AppTest) assert the two columns' actual rendered pixel
    widths; it proves st.columns(...) accepts every PANEL_RATIOS value
    without raising and the rest of the view still renders. resume_data is
    left empty (the fresh-session default) so this never touches the real
    lualatex compile path, matching
    test_generator_preview.py's test_empty_base_resume_compiles_nothing."""
    for preset in PANEL_RATIO_PRESETS:
        at = run_app(active_view="Generator", panel_ratio=preset)
        assert not at.exception
        assert ratio_control(at).value == preset
        # Sanity: the rest of the Generator view still renders alongside it.
        assert any(h.value == "Export Settings" for h in at.subheader)
