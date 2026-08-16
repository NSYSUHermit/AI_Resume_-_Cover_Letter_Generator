"""Coverage for render_preview() (app.py) after UI Task 2 - the right column
that used to hold Export Settings + a "Preview"/"ATS" tab pair now holds only
render_preview() itself: a top-left Target switch, a top-right download
button, and the rendered PDF. Export Settings and the ATS analysis moved to
the bottom of the left column (render_generator_workspace()).

The main behaviour under test is the performance requirement from the design
doc (docs/superpowers/specs/2026-08-15-generator-ui-polish-design.md, "一、
未優化前的預覽必須快取，不能急切編譯"): before anything is optimized, the right
column shows a preview of the *base* resume so it isn't empty on arrival, but
that preview is wrapped in `@st.cache_data` (base_preview_pdf, app.py) keyed
on resume_snapshot() + template + block order, because the underlying
generate_preview_pdf_bytes() shells out to `subprocess.run(['lualatex', ...])`
- multiple seconds of work that must not happen on every rerun.

On monkeypatching strategy: AppTest.from_file() executes app.py fresh on every
at.run() as the "__main__" module (streamlit/runtime/scriptrunner/script_runner.py,
_new_module/sys.modules["__main__"]), not as a normally-imported "app" module
registered in sys.modules under that name - confirmed by reading that source
directly. That means a function defined *inside* app.py (generate_preview_pdf_bytes,
base_preview_pdf) cannot be monkeypatched by dotted path the way
tests/test_tracker_guard.py patches firebase_dashboard.init_firebase /
.save_application (those work because firebase_dashboard is a normally
importable module app.py pulls names from, re-imported fresh on every rerun
after the monkeypatch is already in place). Every test below instead patches
`subprocess.run` directly - `subprocess` is a real singleton stdlib module,
unaffected by app.py's own re-execution, and it is also literally the
expensive operation the design doc is about (its own words: "shells out to
subprocess.run(['lualatex', ...])"), so counting its invocations is a more
direct proxy for "did we pay the compilation cost" than counting calls to the
Python function that wraps it.

Confirmed empirically (scratch script, not part of this file) that
st.cache_data's storage is a process-wide singleton that survives across
separate AppTest instances, not just across .run() calls on the same
instance - two independent AppTest objects built from identical resume
content produced a cache hit on the second one. Every test therefore gives
its resume a unique `heading.name` so its cache key can never collide with
another test's, regardless of test execution order.
"""
import os
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


def resume_with_experience(name):
    """A minimal non-empty resume - just enough for resume_is_empty() to say
    False, so render_preview() takes the base-preview branch instead of the
    empty-state branch."""
    return {
        "heading": {"name": name, "email": "", "phone": "", "website": "", "linkedin": ""},
        "summary": "",
        "education": [],
        "experience": [{"title": "Engineer", "company": "Acme", "time_period": "2020-2024", "bullets": ["Did things"]}],
        "projects": [],
        "patents": [],
        "skills": {"set1": {"title": "Skills", "items": []}},
        "cover_letter": "",
        "target_company": "",
        "target_role": "",
        "about me more": "",
    }


def fake_lualatex(calls):
    """A stand-in for `subprocess.run(['lualatex', ...])` that appends every
    invocation's argv to `calls` and writes the .pdf file
    generate_preview_pdf_bytes expects to find afterwards (op = tp with .tex
    replaced by .pdf), so a "successful" fake compile returns real bytes and
    a cache entry actually gets stored - not just a cached None."""
    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(cmd, cwd=None, capture_output=None, text=None, **kwargs):
        calls.append(cmd)
        pdf_name = cmd[-1].replace(".tex", ".pdf")
        with open(os.path.join(cwd, pdf_name), "wb") as f:
            f.write(b"%PDF-1.4 fake")
        return FakeCompletedProcess()

    return run


def test_base_preview_is_cached_and_compiles_at_most_once(monkeypatch):
    """The performance requirement this task exists for: rendering the
    Generator view twice with an unchanged resume must invoke the expensive
    lualatex subprocess at most once, not once per rerun. The first .run()
    (inside run_app) is a guaranteed cache miss - this resume's name has
    never been seen before by the process-wide cache; the second .run(),
    with session_state otherwise untouched, must be a cache hit."""
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))

    at = run_app(active_view="Generator", resume_data=resume_with_experience("Cache Probe Candidate"))
    assert not at.exception
    assert len(calls) == 1

    at.run()
    assert not at.exception
    assert len(calls) == 1  # unchanged resume -> second render must be a cache hit


def test_base_preview_show_spinner_change_preserves_hit_miss_semantics(monkeypatch):
    """UI Task 4 closed a gap this task's own design doc left: base_preview_pdf
    used to be @st.cache_data(show_spinner=False, ...), so a genuine first-time
    compile ran for several seconds with no visible indication anything was
    happening at all. The fix is show_spinner="Compiling your resume
    preview..." instead of False - st.cache_data's own show_spinner mechanism
    is hit/miss-aware at the framework level (it wraps only the cache-miss
    code path; a hit returns before that wrapping is even constructed - see
    streamlit/runtime/caching/cache_utils.py's
    CachedFunc._get_or_create_cached_value()), so this is a pure display-layer
    change with no cache-keying effect of its own. This test cannot observe
    the spinner itself - st.cache_data's own show_spinner UI is transient and
    AppTest only captures the tree after a full script run completes, the
    same reason test_base_preview_is_cached_and_compiles_at_most_once (above)
    already could not either - but it extends that test's counter-based proof
    with the one thing that test alone does not cover: that a genuinely
    *different* resume still forces a real recompile (the fix did not
    accidentally make every call look like a hit), and that switching back to
    the first resume is still served from its own untouched cache entry (the
    fix did not accidentally make every call look like a miss, or evict
    unrelated entries)."""
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))

    resume_a = resume_with_experience("Spinner Semantics Candidate A")
    resume_b = resume_with_experience("Spinner Semantics Candidate B")

    at = run_app(active_view="Generator", resume_data=resume_a)
    assert not at.exception
    assert len(calls) == 1  # A: miss

    at.run()
    assert not at.exception
    assert len(calls) == 1  # A again, untouched: hit

    at.session_state["resume_data"] = resume_b
    at.run()
    assert not at.exception
    assert len(calls) == 2  # B: a genuinely different key still misses

    at.session_state["resume_data"] = resume_a
    at.run()
    assert not at.exception
    assert len(calls) == 2  # back to A: still served from its own cache entry


def test_empty_base_resume_compiles_nothing(monkeypatch):
    """resume_is_empty() gates the cached base preview: a first-time user
    with nothing in their Career Profile yet must never pay the lualatex
    cost just for landing on Generator. A fresh session's resume_data is
    default_resume_data(), which is empty, so no override is needed here."""
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))

    at = run_app(active_view="Generator")
    assert not at.exception
    assert calls == []


def test_real_preview_takes_precedence_and_skips_base_compile(monkeypatch):
    """Precedence rule from the design doc: once optimized_resume_data and
    real preview bytes exist, render_preview() must show those, not the base
    preview - and must not even attempt the base compile in that case."""
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))

    at = run_app(
        active_view="Generator",
        resume_data=resume_with_experience("Precedence Candidate"),
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-1.4 real",
        resume_dl_data={"bytes": b"%PDF-1.4 real", "name": "Acme_Role_Resume.pdf"},
    )
    assert not at.exception
    assert calls == []
    assert len(at.download_button) == 1


def test_generator_view_has_no_tabs():
    """After this task the right column contains no tabs - st.tabs() was the
    "Preview"/"ATS" pair inside the old render_generator_panel(), which no
    longer exists. This is the only st.tabs() call site in the whole app
    (confirmed by grep), so this also proves nothing re-introduced one."""
    at = run_app(active_view="Generator", resume_data=resume_with_experience("No Tabs Candidate"))
    assert not at.exception
    assert len(at.tabs) == 0


def target_switch(at):
    """render_preview()'s Resume/Cover Letter switch, found by its own widget
    key ("tr") rather than by list position - UI Task 4 added a second
    st.segmented_control to the Generator view (the panel-ratio control,
    rendered above the two columns and so first in render order), which
    pushed this one from index 0 to index 1. Selecting by key is robust to
    that ordering entirely."""
    matches = [sc for sc in at.segmented_control if sc.key == "tr"]
    assert len(matches) == 1
    return matches[0]


def test_segmented_control_defaults_to_resume():
    """st.segmented_control replaces the old st.radio("Target", ...), which
    defaulted to its first option ("Resume") on a fresh render. Preserve that
    default exactly."""
    at = run_app(active_view="Generator", resume_data=resume_with_experience("Default Target Candidate"))
    assert not at.exception
    # Two segmented controls now live on this view (the panel-ratio switch,
    # UI Task 4, plus this one) - assert count via the panel-ratio test file
    # instead of duplicating that coverage here.
    assert target_switch(at).value == "Resume"


def test_cover_letter_target_before_generation_shows_placeholder():
    """There is no cached "base" version of the cover letter (the design doc
    only asks for one for the base resume), so switching to Cover Letter
    before Generate PDF has run must degrade to an explanatory message, not
    an exception or a blank pane."""
    at = run_app(active_view="Generator", resume_data=resume_with_experience("Cover Letter Candidate"))
    target_switch(at).set_value("Cover Letter").run()
    assert not at.exception
    assert any("preview the cover letter" in i.value for i in at.info)


def test_export_settings_and_ats_moved_into_generator_view():
    """render_export_settings() and the ATS analysis section (formerly the
    right column's "Export Settings" fragment and "ATS" tab) must still
    render somewhere in the Generator view after moving into the bottom of
    the left column - this only proves they're present and wired, not which
    column they're in (AppTest's tree does not make that distinction easy to
    query; the exact placement is a visual claim, listed as unverified in the
    task report)."""
    at = run_app(active_view="Generator", resume_data=resume_with_experience("Export Settings Candidate"))
    assert not at.exception
    assert any(h.value == "Export Settings" for h in at.subheader)
    assert any("Optimize a resume to see how it scores" in c.value for c in at.caption)
