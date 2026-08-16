"""Coverage for UI Task 3: the optimized result as a directly-editable draft
table (render_optimized_draft_table(), app.py) and the quick-stats cards
above Source of Truth (render_quick_stats(), app.py).

On simulating st.data_editor edits with AppTest: streamlit==1.61.1's
streamlit.testing.v1.element_tree has no typed wrapper for st.data_editor -
st.dataframe/st.data_editor both parse to the same read-only `Dataframe`
Element (arrow_data_frame proto), which exposes `.value` but no `.input()`/
`.set_value()` the way TextArea, Checkbox etc. do (confirmed by reading
element_tree.py: `class Dataframe(Element)`, not `Widget`). Every test below
instead presets st.session_state[<data_editor key>] directly to an
`EditingState`-shaped dict - {"edited_rows": {row_index: {col: value}},
"added_rows": [...], "deleted_rows": [...]} - before calling .run().

This works because a data_editor's session_state entry does not hold the
edited data itself; it holds this diff structure, which
streamlit.elements.widgets.data_editor._apply_dataframe_edits() applies to
the seed data to produce the widget's actual return value. Setting
session_state[key] directly to this shape before the widget is first
instantiated is the exact same mechanism every other test file in this suite
already relies on for plain (non-widget) session_state keys (see e.g.
test_tracker_guard.py's run_app(**session_overrides)) - Streamlit seeds a
widget's value from session_state whenever the key already has one, rather
than from the value passed at the call site. Confirmed empirically with a
standalone scratch script (not committed) before writing these tests: an
untouched st.data_editor (fresh key, no preset session_state) returns its
seed unchanged on every rerun, and a preset EditingState dict round-trips
into the widget's return value exactly as the real frontend's diff protocol
would produce.
"""
import json
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
    # UI item 2 moved the draft table behind a dialog (render_optimized_
    # draft_table(), app.py, now @st.dialog-decorated, opened by the
    # "Draft Table" button keyed "open_draft_table_dialog"). Every test
    # below that inspects the table's own widgets or its "Optimized Draft"
    # markdown needs it open first - doing that once here, right after the
    # initial run, covers every test that reads the table immediately
    # after run_app() returns with no further .run() of its own.
    #
    # Tests that ALSO preset a data_editor's (or plain widget's)
    # session_state and call .run() again afterward need one more step of
    # their own: see reopen_draft_table() below. A bare .run() consumes the
    # opener button's one-shot click, so without re-staging it, that
    # additional run re-evaluates `if st.button(...): render_optimized_
    # draft_table()` fresh, finds the button not clicked, and closes the
    # dialog again before the widget inside it is even instantiated - so
    # any preset staged for that widget is never processed. Same mechanism
    # test_tracker_guard.py's
    # test_advanced_optimized_json_import_resets_tracked_application_id
    # documents for edit_opt_dialog(), the sibling dialog beside this one.
    # Confirmed empirically (all six affected tests below failed with a
    # bare .run() here, before adding reopen_draft_table()) before writing
    # it this way.
    openers = [b for b in at.button if b.key == "open_draft_table_dialog"]
    if openers:
        openers[0].click().run()
    return at


def reopen_draft_table(at):
    """Re-stage a click on the Draft Table opener button before an
    additional at.run(). See run_app()'s own comment above for why a bare
    .run() would otherwise close the dialog before a preset data_editor (or
    other widget) edit inside it is ever processed."""
    openers = [b for b in at.button if b.key == "open_draft_table_dialog"]
    assert len(openers) == 1, "Draft Table opener button not found - is the dialog already open, or the table absent?"
    openers[0].click()


def forbid_subprocess(*args, **kwargs):
    """Monkeypatch target for tests that set a non-empty resume_data but do
    not care about the base-resume preview: render_preview() (the right
    column) renders unconditionally alongside render_generator_workspace()
    (the left column, where the draft table and quick stats live), and would
    shell out to a REAL `lualatex` (installed on this machine, confirmed by
    tests/test_generator_preview.py's docstring) if resume_data is non-empty
    and no real preview bytes are already set. Every test below that uses a
    non-empty resume_data also sets resume_preview_bytes so render_preview()
    never reaches that branch - this monkeypatch is the belt-and-suspenders
    backstop in case that reasoning is ever wrong, failing loudly and fast
    instead of hanging on a real multi-second compile."""
    raise AssertionError("must not shell out to lualatex in this test")


def optimized_with_one_role(**overrides):
    data = {
        "target_company": "Acme",
        "target_role": "Engineer",
        "heading": {},
        "skills": {},
        "experience": [
            {
                "company": "OldCo",
                "role": "SWE",
                "time_duration": "2020-2024",
                "company_location": "SF",
                "details": [{"description": "Did a thing"}],
            }
        ],
    }
    data.update(overrides)
    return data


def resume_with_two_roles():
    return {
        "heading": {"name": "Quick Stats Candidate", "email": "", "phone": "", "website": "", "linkedin": ""},
        "summary": "",
        "education": [],
        "experience": [
            {"company": "Acme", "role": "Engineer", "time_duration": "2020-2022", "company_location": "", "details": []},
            {"company": "Globex", "role": "Senior Engineer", "time_duration": "2022-2024", "company_location": "", "details": []},
        ],
        "projects": [],
        "patents": [],
        "skills": {"set1": {"title": "Skills", "items": []}},
        "cover_letter": "",
        "target_company": "",
        "target_role": "",
        "about me more": "",
    }


# ---------------------------------------------------------------------------
# Draft table: the round trip (this feature's whole point)
# ---------------------------------------------------------------------------

def test_draft_table_edit_lands_in_optimized_resume_data():
    """A cell edit in the draft table must flow into
    st.session_state.optimized_resume_data - not just render a widget."""
    at = run_app(active_view="Generator", optimized_resume_data=optimized_with_one_role())
    ekey = at.session_state["opt_editor_key"]
    exp_key = f"draft_experience_{ekey}"

    at.session_state[exp_key] = {
        "edited_rows": {0: {"company": "New Corp"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    reopen_draft_table(at)
    at.run()

    assert not at.exception
    experience = at.session_state["optimized_resume_data"]["experience"]
    assert experience[0]["company"] == "New Corp"
    # Editing one cell must not disturb the rest of that row.
    assert experience[0]["role"] == "SWE"
    assert experience[0]["time_duration"] == "2020-2024"


def test_draft_table_scalar_input_lands_in_optimized_resume_data():
    """The labelled Target Company/Role/Summary inputs above the table use
    the same auto-save write-back as the grids - covers that path too, not
    just st.data_editor."""
    at = run_app(active_view="Generator", optimized_resume_data=optimized_with_one_role())
    ekey = at.session_state["opt_editor_key"]

    at.text_input(key=f"draft_company_{ekey}").input("Globex Corp")
    reopen_draft_table(at)
    at.run()

    assert not at.exception
    assert at.session_state["optimized_resume_data"]["target_company"] == "Globex Corp"


def test_draft_table_edit_to_skills_lands_in_optimized_resume_data():
    """Skills round-trips through skills_to_rows()/rows_to_skills(), the
    same helpers whose schema-normalisation motivated comparing against a
    recomputed baseline instead of the raw dict (see
    render_optimized_draft_table()'s docstring). A genuine edit here must
    still be detected as a real change despite that normalisation."""
    optimized = optimized_with_one_role(
        skills={"set1": {"title": "Languages", "items": ["Python"]}},
    )
    at = run_app(active_view="Generator", optimized_resume_data=optimized)
    ekey = at.session_state["opt_editor_key"]
    skills_key = f"draft_skills_{ekey}"

    at.session_state[skills_key] = {
        "edited_rows": {0: {"items": "Python, Go, Rust"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    reopen_draft_table(at)
    at.run()

    assert not at.exception
    assert at.session_state["optimized_resume_data"]["skills"]["set1"]["items"] == ["Python", "Go", "Rust"]


def test_draft_table_preserves_fields_it_does_not_manage():
    """heading, cover_letter and patents are out of this table's scope (see
    render_optimized_draft_table()'s docstring) - they must survive a table
    edit byte-for-byte, passed through via **current."""
    optimized = optimized_with_one_role(
        heading={"name": "Jane Doe", "email": "jane@x.com"},
        cover_letter="Dear hiring manager...",
        patents=[{"name": "Patent1", "time": "2022", "description": "A patent"}],
    )
    at = run_app(active_view="Generator", optimized_resume_data=optimized)
    ekey = at.session_state["opt_editor_key"]
    exp_key = f"draft_experience_{ekey}"

    at.session_state[exp_key] = {
        "edited_rows": {0: {"role": "Senior SWE"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    reopen_draft_table(at)
    at.run()

    assert not at.exception
    result = at.session_state["optimized_resume_data"]
    assert result["experience"][0]["role"] == "Senior SWE"
    assert result["heading"] == {"name": "Jane Doe", "email": "jane@x.com"}
    assert result["cover_letter"] == "Dear hiring manager..."
    assert result["patents"] == [{"name": "Patent1", "time": "2022", "description": "A patent"}]


# ---------------------------------------------------------------------------
# Draft table: the false-positive bug found and fixed during self-review
# ---------------------------------------------------------------------------

def test_draft_table_does_not_clear_a_freshly_generated_pdf_on_first_render():
    """Regression test for a bug caught before this was committed: comparing
    the draft table's reconstructed value against the RAW
    optimized_resume_data (instead of a `baseline` run through the same
    seed/compact-rows pipeline) treated schema normalisation alone -
    skills_to_rows()/rows_to_skills() turning a missing/empty "skills" dict
    into a non-empty default - as an "edit" on every single render, even
    with zero user interaction. That called clear_pdf_outputs() the moment
    the table first rendered, silently wiping resume_dl_data /
    resume_preview_bytes for a result the user never touched.

    This uses the exact sparse optimized_resume_data shape
    (`{"target_company": "Acme"}`, no "skills"/"experience"/"education"/
    "projects" keys at all) that several tests in test_tracker_guard.py
    already set up alongside pre-generated PDF bytes and depend on for their
    own download-button assertions - if this bug were reintroduced, those
    tests would fail too, but this test pins the mechanism down directly."""
    at = run_app(
        active_view="Generator",
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake-resume",
        resume_dl_data={"bytes": b"%PDF-fake-resume", "name": "Acme_Role_Resume.pdf"},
    )
    assert not at.exception
    assert at.session_state["resume_preview_bytes"] == b"%PDF-fake-resume"
    assert at.session_state["resume_dl_data"] is not None
    assert len(at.download_button) == 1
    # The table itself must still show the real data, not have silently
    # rewritten it either.
    assert at.session_state["optimized_resume_data"]["target_company"] == "Acme"


def test_draft_table_edit_clears_stale_pdf_but_keeps_tracked_flag():
    """The flip side of the test above: a GENUINE edit must invalidate any
    already-generated PDF (it was built from the pre-edit data) -
    clear_pdf_outputs() firing here matches edit_opt_dialog()'s Save Changes
    handler exactly. But editing the current result in place is still the
    same application, not a new one (clear_pdf_outputs_and_tracking()'s own
    docstring), so tracked_application_id - the tracker dedupe guard - must
    NOT reset, unlike the three manual-import paths."""
    at = run_app(
        active_view="Generator",
        optimized_resume_data=optimized_with_one_role(),
        resume_preview_bytes=b"%PDF-fake-resume",
        resume_dl_data={"bytes": b"%PDF-fake-resume", "name": "Acme_Role_Resume.pdf"},
        tracked_application_id="Acme",
        logged_in=True,
    )
    ekey = at.session_state["opt_editor_key"]
    exp_key = f"draft_experience_{ekey}"

    at.session_state[exp_key] = {
        "edited_rows": {0: {"company": "NewCo"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    reopen_draft_table(at)
    at.run()

    assert not at.exception
    assert at.session_state["optimized_resume_data"]["experience"][0]["company"] == "NewCo"
    assert at.session_state["resume_preview_bytes"] is None
    assert at.session_state["resume_dl_data"] is None
    assert at.session_state["tracked_application_id"] == "Acme"


def test_draft_table_absent_without_optimized_result():
    """A fresh session with nothing optimized yet must not render the draft
    table at all - it lives inside `if st.session_state.optimized_resume_data:`."""
    at = run_app(active_view="Generator")
    assert not at.exception
    assert not any("Optimized Draft" in m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# UI final-review fix wave, Important 4: the draft table must degrade rather
# than crash on JSON shapes the merge base tolerated. optimized_resume_data
# reaches this table with zero shape validation from three places - Manual
# Data Import and Manual Result Import (both parse arbitrary pasted JSON,
# see their own st.caption()s in app.py) and ai.rewrite_resume() (ai.py,
# whose FORMAT block shows "education": [] etc. with no element schema) -
# so a bare list of strings where the table expects a list of dicts, or a
# JSON array instead of an object at the top level, both have to be
# survivable. Confirmed against a copy of app.py with the compact_rows()/
# current-isinstance guards reverted that all three reproduce
# AttributeError: 'str'/'list' object has no attribute 'get' before writing
# these tests.
# ---------------------------------------------------------------------------

def test_draft_table_survives_education_as_list_of_strings():
    """{"education": ["MIT BS"]} - a plausible hand-pasted shortcut, and
    exactly the kind of thing Manual Data Import's free-form JSON invites -
    used to crash compact_rows() (row.get(...) on the string "MIT BS") on
    every single render, taking down everything render_generator_workspace()
    draws after it, including the only two surfaces that could fix the bad
    data (Manual Data Import itself and Edit Optimized JSON)."""
    at = run_app(active_view="Generator", optimized_resume_data={"education": ["MIT BS"]})
    assert not at.exception
    assert any("Optimized Draft" in m.value for m in at.markdown)


def test_draft_table_survives_projects_as_list_of_strings():
    """Same shape of bug, the other field the finding named: {"projects":
    ["p1"]} crashed the same way, one function call later
    (compact_rows(project_rows, PROJECT_ROW_FIELDS))."""
    at = run_app(active_view="Generator", optimized_resume_data={"projects": ["p1"]})
    assert not at.exception
    assert any("Optimized Draft" in m.value for m in at.markdown)


def test_draft_table_survives_list_shaped_optimized_resume_data():
    """optimized_resume_data itself does not have to be an object - a JSON
    array pasted into Manual Data Import satisfies "if
    st.session_state.optimized_resume_data:" (a non-empty list is truthy)
    just as well as a dict does, and used to crash the very first
    current.get(...) call (current = the list itself; render_optimized_draft_table()
    now coerces a non-dict current to {} before this point)."""
    at = run_app(active_view="Generator", optimized_resume_data=["p1"])
    assert not at.exception
    assert any("Optimized Draft" in m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# UI final-review fix wave, Important 5: details_to_text() must not explode
# a string "details" into one row per character.
# ---------------------------------------------------------------------------

def test_draft_table_string_details_survive_an_unrelated_cell_edit():
    """experience[0]["details"] as a bare string (not a list of
    {"description": ...} dicts - reachable the same three ways as the shapes
    above) used to survive seeding the table (details_to_text() iterated the
    string character by character but nothing forced a write-back yet), then
    get silently shredded into one {"description": <single char>} entry per
    non-space character the moment ANY other cell in the table was edited -
    here, an unrelated field (role) - because that edit is what makes
    render_optimized_draft_table() compare `updated` against `baseline` as
    genuinely different and write `updated` back into
    st.session_state.optimized_resume_data. Confirmed against a copy of
    details_to_text() with its isinstance(details, str) branch reverted that
    this exact edit turns "Led the migration.\\nCut latency 40%." into 30
    single-character entries before writing this test."""
    optimized = optimized_with_one_role()
    optimized["experience"][0]["details"] = "Led the migration.\nCut latency 40%."
    at = run_app(active_view="Generator", optimized_resume_data=optimized)
    ekey = at.session_state["opt_editor_key"]
    exp_key = f"draft_experience_{ekey}"

    at.session_state[exp_key] = {
        "edited_rows": {0: {"role": "Senior SWE"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    reopen_draft_table(at)
    at.run()

    assert not at.exception
    experience = at.session_state["optimized_resume_data"]["experience"]
    assert experience[0]["role"] == "Senior SWE"
    assert experience[0]["details"] == [
        {"description": "Led the migration."},
        {"description": "Cut latency 40%."},
    ]


# ---------------------------------------------------------------------------
# Manual-import reseeding: opt_editor_key must bump on all wholesale
# replacements, not only Optimize Resume and the dialog's own two paths
# ---------------------------------------------------------------------------

def test_manual_result_import_reseeds_draft_table_instead_of_clobbering_it():
    """Without the `st.session_state.opt_editor_key += 1` line added to the
    Manual Result Import handler (app.py), the draft table's data_editor
    keeps rendering under its OLD widget key after a wholesale replacement,
    so a stale edit still sitting in that old widget's session_state gets
    written straight back into optimized_resume_data on the very next
    render - silently overwriting the freshly imported JSON with leftovers
    from the PREVIOUS result. Confirmed manually against a copy of app.py
    with that line removed that this exact scenario reproduces the failure
    (experience company stays "StaleEdit" instead of becoming "GlobexCo")
    before writing this test."""
    first = optimized_with_one_role(target_company="FirstCo")
    at = run_app(active_view="Generator", optimized_resume_data=first, show_advanced_tools=True)
    ekey0 = at.session_state["opt_editor_key"]
    exp_key0 = f"draft_experience_{ekey0}"
    # A stale edit sitting in the OLD widget's state - as if the table had
    # rendered with an edit that had not yet triggered its own standalone
    # rerun before the import button was clicked.
    at.session_state[exp_key0] = {
        "edited_rows": {0: {"company": "StaleEdit"}},
        "added_rows": [],
        "deleted_rows": [],
    }

    manual_json_inputs = [t for t in at.text_area if t.key == "manual_ats_json"]
    assert len(manual_json_inputs) == 1
    manual_json_inputs[0].input(json.dumps({
        "optimized_resume": {
            "target_company": "Globex",
            "heading": {},
            "skills": {},
            "experience": [{"company": "GlobexCo", "role": "PM", "time_duration": "", "company_location": "", "details": []}],
        }
    })).run()
    apply_buttons = [b for b in at.button if b.label == "Apply Manual Result"]
    assert len(apply_buttons) == 1
    apply_buttons[0].click().run()

    assert not at.exception
    result = at.session_state["optimized_resume_data"]
    assert result["target_company"] == "Globex"
    assert result["experience"][0]["company"] == "GlobexCo"
    assert at.session_state["opt_editor_key"] == ekey0 + 1


def test_manual_data_import_reseeds_draft_table_instead_of_clobbering_it():
    """Same regression as above, the other manual-import site (Manual Data
    Import, which replaces optimized_resume_data with the pasted JSON
    directly rather than unwrapping an "optimized_resume" key)."""
    first = optimized_with_one_role(target_company="FirstCo")
    at = run_app(active_view="Generator", optimized_resume_data=first, show_advanced_tools=True)
    ekey0 = at.session_state["opt_editor_key"]
    exp_key0 = f"draft_experience_{ekey0}"
    at.session_state[exp_key0] = {
        "edited_rows": {0: {"company": "StaleEdit"}},
        "added_rows": [],
        "deleted_rows": [],
    }

    manual_data_inputs = [t for t in at.text_area if t.key == "manual_opt_input"]
    assert len(manual_data_inputs) == 1
    manual_data_inputs[0].input(json.dumps({
        "target_company": "Globex",
        "heading": {},
        "skills": {},
        "experience": [{"company": "GlobexCo", "role": "PM", "time_duration": "", "company_location": "", "details": []}],
    })).run()
    apply_buttons = [b for b in at.button if b.label == "Apply Manual Data"]
    assert len(apply_buttons) == 1
    apply_buttons[0].click().run()

    assert not at.exception
    result = at.session_state["optimized_resume_data"]
    assert result["target_company"] == "Globex"
    assert result["experience"][0]["company"] == "GlobexCo"
    assert at.session_state["opt_editor_key"] == ekey0 + 1


# ---------------------------------------------------------------------------
# Quick stats
# ---------------------------------------------------------------------------

def test_quick_stats_render_without_error_when_logged_out_and_profile_empty():
    """Required test: a fresh, logged-out session with an empty profile must
    render the quick-stats row without error, showing only the one real,
    always-sourceable number (Experience Entries - genuinely 0 for an empty
    profile, not a fabricated placeholder), with no ATS-score or
    applications-recorded card at all."""
    at = run_app(active_view="Generator")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert labels == ["Experience Entries"]
    assert at.metric[0].value == "0"


def test_quick_stats_omit_ats_score_and_applications_when_neither_exists():
    """Same no-fabrication rule for a logged-in session that has never
    optimized or visited Tracker: ats_metrics is None and app_records was
    never populated, so both conditional cards must be absent rather than a
    fake 0% / 0 applications."""
    at = run_app(active_view="Generator", logged_in=True, user_email="a@b.com")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Latest ATS Score" not in labels
    assert "Applications Recorded" not in labels


def test_quick_stats_show_real_experience_count(monkeypatch):
    """Experience Entries reflects the real base-profile count. subprocess.run
    is monkeypatched defensively (see forbid_subprocess()'s docstring) so a
    non-empty resume_data can never trigger a real lualatex compile from
    render_preview(), the right column, which renders unconditionally
    alongside the left column this test actually cares about."""
    monkeypatch.setattr("subprocess.run", forbid_subprocess)
    at = run_app(
        active_view="Generator",
        resume_data=resume_with_two_roles(),
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "x.pdf"},
    )
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["Experience Entries"] == "2"


def test_quick_stats_show_real_ats_score_when_available():
    metrics = {
        "total": 10,
        "original_count": 3,
        "optimized_count": 7,
        "original_pct": 30,
        "optimized_pct": 70,
        "optimized_hits": [],
        "newly_added": [],
        "missing_keywords": [],
    }
    at = run_app(active_view="Generator", ats_metrics=metrics)
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["Latest ATS Score"] == "70%"


def test_quick_stats_show_applications_recorded_when_cached_and_logged_in():
    """Applications Recorded only reads what is already cached in
    session_state (app_records) - deliberately no new Firestore fetch is
    triggered from the quick-stats row itself; see render_quick_stats()'s
    docstring for why."""
    at = run_app(
        active_view="Generator",
        logged_in=True,
        app_records=[{"company": "Acme"}, {"company": "Globex"}, {"company": "Initech"}],
    )
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["Applications Recorded"] == "3"


def test_quick_stats_omit_applications_recorded_when_logged_out_even_if_cached():
    """app_records can survive as an empty (or, as reproduced here, even a
    non-empty) list across logout - clear_user_session() sets it to [], it
    does not delete the key. The logged_in check in render_quick_stats() must
    be independent of key-presence, not redundant with it - otherwise a
    stale cache from a previous account on the same browser session could
    leak a number into a logged-out session."""
    at = run_app(active_view="Generator", logged_in=False, app_records=[{"company": "Acme"}])
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Applications Recorded" not in labels
