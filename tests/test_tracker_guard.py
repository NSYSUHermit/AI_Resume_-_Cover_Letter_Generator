"""Regression coverage for the Tracker recording guard's *wiring* in app.py.

workspace.should_record_application() itself is unit-tested across all four
boolean combinations in test_workspace.py. What isn't covered anywhere else is
the wiring around it inside app.py: that sync_application_to_tracker() only
flips st.session_state.tracked_application_id after save_application() has
actually run and returned success (never optimistically), that the guard
reads the real st.session_state.logged_in rather than a proxy, that a second
download while already tracked never attempts a second write, and that
clear_generated_outputs() resets the flag so a fresh Optimize run starts a
fresh application.

Most of this needs no Firestore at all: there is no .streamlit/secrets.toml
on this machine, so get_db() always returns None here, and several
assertions below lean on exactly that fact. Two tests
(test_failed_write_does_not_record, test_successful_write_sets_flag_and_survives_the_rerun)
monkeypatch firebase_dashboard.init_firebase / .save_application directly, to
reach the True/False branches of save_application()'s own return value —
something that is otherwise unreachable locally, since get_db() being None
always short-circuits before save_application() is ever called. Neither
patch fakes a Firestore client or asserts anything about Firestore's real
duplicate-prevention (see the module-level docstrings on those two tests for
exactly what is and isn't being claimed); the two Firestore-dependent
checklist items (consecutive resume+cover-letter downloads producing exactly
one row, and a second Optimize run producing a second row) remain deferred to
deployment, as recorded in task-6-report.md.

The final whole-branch review (Finding 1) found a related hole: three sites
replace optimized_resume_data wholesale — Manual Result Import, Manual Data
Import, and the Advanced Optimized JSON Import inside edit_opt_dialog — but
only cleared the PDF outputs, not tracked_application_id. A stale flag from
the *previous* application silently blocked should_record_application() from
recording the new one on the next download, with no way to recover the
missing row (firebase_dashboard.py has no manual add-application UI). The
three test_*_import_resets_tracked_application_id tests below cover all
three sites and were each confirmed to fail (flag stays "Acme" instead of
going back to None) against the pre-fix code before being committed.
"""
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

# Same anchoring rationale as test_app_smoke.py: AppTest.from_file resolves a
# relative path against this file's directory, not the process cwd.
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


def test_tracked_application_id_starts_none():
    at = run_app()
    assert not at.exception
    assert at.session_state["tracked_application_id"] is None


def test_download_while_logged_out_does_not_record():
    """The guard must read the real logged_in flag, not a proxy: an
    unauthenticated download must never flip tracked_application_id, and must
    never even reach Firestore — should_record_application() short-circuits
    before get_db() is called, so no error is surfaced either."""
    at = run_app(
        active_view="Generator",
        logged_in=False,
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Acme_Role_Resume.pdf"},
    )
    assert len(at.download_button) == 1
    at.download_button[0].click().run()
    assert not at.exception
    assert at.session_state["tracked_application_id"] is None
    assert len(at.error) == 0


def test_download_while_logged_in_but_tracker_unavailable_does_not_record():
    """Guard passes (logged in, not yet tracked), but get_db() is None
    locally (no secrets.toml) — sync_application_to_tracker() must stop at
    the "Tracker is unavailable" branch and never reach save_application() at
    all. The flag must stay None.

    This does NOT exercise the `ok` check that runs after save_application()
    returns — execution never gets that far in this scenario, since it stops
    at the earlier `tracker_db is None` check. That branch is covered
    separately by test_failed_write_does_not_record, which monkeypatches
    save_application() itself so execution can reach it. (An earlier version
    of this test's docstring incorrectly claimed to cover that branch; see
    task-6-report.md's Finding 1 fix notes.)"""
    at = run_app(
        active_view="Generator",
        logged_in=True,
        user_email="test@example.com",
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Acme_Role_Resume.pdf"},
    )
    at.download_button[0].click().run()
    assert not at.exception
    assert at.session_state["tracked_application_id"] is None
    assert any("Tracker is unavailable" in e.value for e in at.error)


def test_download_when_already_tracked_does_not_attempt_second_write():
    """The 'then blocks' half of the dedupe guard — and the one behaviour
    this entire task exists to guarantee. Once tracked_application_id is
    already set, a second download must not even attempt a write.

    If the guard failed to block here, execution would reach
    get_db() -> None (locally) -> surface "Tracker is unavailable". Its
    absence is the proof the guard held; if it ever appears in this
    scenario, the guard broke."""
    at = run_app(
        active_view="Generator",
        logged_in=True,
        tracked_application_id="Acme",
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Acme_Role_Resume.pdf"},
    )
    at.download_button[0].click().run()
    assert not at.exception
    assert not any("Tracker is unavailable" in e.value for e in at.error)
    assert at.session_state["tracked_application_id"] == "Acme"


def test_failed_write_does_not_record(monkeypatch):
    """save_application() can return False without raising — it catches its
    own exceptions internally (firebase_dashboard.py). The flag must only be
    set after a *verified success*, never merely because save_application()
    was called. This is exactly what distinguishes the shipped
    `if not ok: return` guard from the brief's literal Step 3 snippet, which
    set the flag unconditionally right after the call returned — confirmed
    by literally reverting to that snippet in a scratch copy of app.py and
    re-running this exact scenario against it: the flag gets set to "Acme"
    there even though save_application() returned False. Against the shipped
    code it stays None.

    Nothing about Firestore itself is faked here: firebase_dashboard.save_application
    is monkeypatched directly to return False, standing in for the many real
    reasons a write can fail (permissions, quota, a network blip) without
    raising — save_application()'s own documented contract is "return a
    bool, never raise". This tests app.py's handling of that contract, not
    Firestore's behaviour, and it says nothing about the two Firestore-
    dependent checklist items (consecutive-download and re-Optimize dedupe),
    which remain deferred to deployment.

    init_firebase is also monkeypatched, to a bare non-None sentinel, purely
    so tracker_db is not None and execution reaches save_application() at
    all — only the boolean save_application() returns is under test here.

    Without the "Tracker is unavailable" negative-assertion below, this test
    would still pass even if the init_firebase monkeypatch silently failed to
    take effect: get_db() would fall back to the real (None-returning) local
    init_firebase, execution would stop at the earlier "Tracker is
    unavailable" branch instead of ever reaching save_application(), and
    tracked_application_id would still end up None — a false green that
    proves nothing about the ok-check this test exists to cover (Finding 4).
    """
    at = run_app(
        active_view="Generator",
        logged_in=True,
        user_email="test@example.com",
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Acme_Role_Resume.pdf"},
    )
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: object())
    monkeypatch.setattr("firebase_dashboard.save_application", lambda *a, **k: False)

    at.download_button[0].click().run()
    assert not at.exception
    # Proves execution actually reached the ok-check past get_db(), rather
    # than short-circuiting at the earlier "tracker_db is None" branch.
    assert not any("Tracker is unavailable" in e.value for e in at.error)
    assert at.session_state["tracked_application_id"] is None


def test_successful_write_sets_flag_and_survives_the_rerun(monkeypatch):
    """The success path — flag assignment, queuing pending_toast, and the
    app-scope st.rerun() added to fix Finding 3 (the "Saved to tracker"
    progress row not updating from inside a fragment) — has no coverage
    otherwise: get_db() is always None locally, so
    sync_application_to_tracker() can only naturally reach its early-return
    branches, never save_application()'s success branch.
    firebase_dashboard.save_application is monkeypatched directly to return
    True to reach those lines and confirm they run without raising and do
    what they say.

    This proves app.py's own bookkeeping after a successful call is correct.
    It does NOT prove anything about Firestore's real duplicate-prevention
    (those checklist items stay deferred to deployment), and it cannot prove
    the st.rerun() actually lands as an app-scope, not fragment-scoped,
    rerun in a real browser — AppTest always executes the full script
    regardless of fragment scoping (there is no partial-rerun distinction to
    observe here), so that specific claim is argued from Streamlit's own
    source in task-6-report.md's Finding 3 fix notes, not from this test.
    """
    at = run_app(
        active_view="Generator",
        logged_in=True,
        user_email="test@example.com",
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Acme_Role_Resume.pdf"},
    )
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: object())
    monkeypatch.setattr("firebase_dashboard.save_application", lambda *a, **k: True)

    at.download_button[0].click().run()
    assert not at.exception
    assert at.session_state["tracked_application_id"] == "Acme"
    assert any("Recorded to tracker." in t.value for t in at.toast)


def test_clear_generated_outputs_resets_tracked_application_id():
    """A fresh Optimize run must start a fresh application: clear_generated_outputs()
    is the shared reset point on both the PDF-import and Optimize paths. This drives
    it through the Advanced JSON Import button — the one caller that needs neither a
    live Gemini API key nor network access, so it stays hermetic."""
    at = run_app(
        active_view="Profile",
        show_advanced_tools=True,
        tracked_application_id="Acme",  # simulate an already-recorded application
    )
    assert at.session_state["tracked_application_id"] == "Acme"
    apply_buttons = [b for b in at.button if b.label == "Apply JSON Import"]
    assert len(apply_buttons) == 1
    apply_buttons[0].click().run()
    assert not at.exception
    assert at.session_state["tracked_application_id"] is None


def test_manual_result_import_resets_tracked_application_id():
    """Finding 1, site 1 of 3 — Manual Result Import. Pasting an externally
    inferred result for a different company must not inherit the previous
    application's tracked flag: clear_pdf_outputs_and_tracking() replaces
    the bare clear_pdf_outputs() call here for exactly this reason. Confirmed
    to fail (flag stays "Acme") against the code with a bare
    clear_pdf_outputs() at this site, before clear_pdf_outputs_and_tracking()
    was introduced."""
    at = run_app(
        active_view="Generator",
        show_advanced_tools=True,
        tracked_application_id="Acme",  # simulate an already-recorded application
    )
    manual_json_inputs = [t for t in at.text_area if t.key == "manual_ats_json"]
    assert len(manual_json_inputs) == 1
    manual_json_inputs[0].input(json.dumps({
        "optimized_resume": {"target_company": "Globex", "heading": {}, "skills": {}},
    })).run()
    apply_buttons = [b for b in at.button if b.label == "Apply Manual Result"]
    assert len(apply_buttons) == 1
    apply_buttons[0].click().run()
    assert not at.exception
    assert at.session_state["optimized_resume_data"]["target_company"] == "Globex"
    assert at.session_state["tracked_application_id"] is None


def test_manual_data_import_resets_tracked_application_id():
    """Finding 1, site 2 of 3 — Manual Data Import. Same invariant as
    test_manual_result_import_resets_tracked_application_id, the other
    manual-import expander. Confirmed to fail the same way against the
    pre-fix bare clear_pdf_outputs() at this site."""
    at = run_app(
        active_view="Generator",
        show_advanced_tools=True,
        tracked_application_id="Acme",
    )
    manual_data_inputs = [t for t in at.text_area if t.key == "manual_opt_input"]
    assert len(manual_data_inputs) == 1
    manual_data_inputs[0].input(json.dumps(
        {"target_company": "Globex", "heading": {}, "skills": {}}
    )).run()
    apply_buttons = [b for b in at.button if b.label == "Apply Manual Data"]
    assert len(apply_buttons) == 1
    apply_buttons[0].click().run()
    assert not at.exception
    assert at.session_state["optimized_resume_data"]["target_company"] == "Globex"
    assert at.session_state["tracked_application_id"] is None


def test_advanced_optimized_json_import_resets_tracked_application_id():
    """Finding 1, site 3 of 3 — Advanced Optimized JSON Import, inside
    edit_opt_dialog (this one is NOT behind show_advanced_tools; it lives in
    the "Edit Optimized JSON" dialog instead). Same invariant, reached
    through a dialog, which needs one extra step to drive with AppTest:

    st.dialog wraps its body as a fragment (streamlit/elements/
    dialog_decorator.py). AppTest has no partial-rerun concept — every
    at.run() re-executes the whole script from the top (as
    test_successful_write_sets_flag_and_survives_the_rerun's docstring notes
    above). A naive "open the dialog, then .run() again to interact with a
    widget inside it" sequence therefore closes the dialog on that second
    run: `if st.button("Edit Optimized JSON"): edit_opt_dialog()` is
    re-evaluated fresh, that button's one-shot click was already consumed by
    the first .run(), so edit_opt_dialog() is not called again and its
    widgets vanish from the tree. Confirmed empirically (dialog buttons and
    the JSON editor text_area disappear from at.button / at.text_area after
    such a second .run()) before writing this test differently.

    The workaround below stages all three interactions — re-click "Edit
    Optimized JSON", set the JSON editor's new value, click "Apply Optimized
    JSON Import" — against the one already-rendered tree from opening the
    dialog, then calls .run() exactly once. AppTest folds every staged
    widget change into that single script run, which re-enters
    edit_opt_dialog() and reaches the real Apply handler with the real data.
    This does not reproduce the exact two-interaction sequence a browser
    user would perform (each of which would be its own fragment-scoped
    rerun in the real app), but it does exercise the exact production code
    path under test with AppTest's only available mechanism for it.
    Confirmed to fail (flag stays "Acme") against the pre-fix bare
    clear_pdf_outputs() at this site."""
    at = run_app(
        active_view="Generator",
        tracked_application_id="Acme",
        optimized_resume_data={"target_company": "Acme", "heading": {}, "skills": {}},
    )
    edit_buttons = [b for b in at.button if b.label == "Edit Optimized JSON"]
    assert len(edit_buttons) == 1
    edit_buttons[0].click().run()
    assert not at.exception

    edit_buttons_again = [b for b in at.button if b.label == "Edit Optimized JSON"]
    json_inputs = [t for t in at.text_area if t.key and t.key.startswith("opt_json_import_")]
    apply_buttons = [b for b in at.button if b.label == "Apply Optimized JSON Import"]
    assert len(edit_buttons_again) == 1
    assert len(json_inputs) == 1
    assert len(apply_buttons) == 1

    edit_buttons_again[0].click()
    json_inputs[0].input(json.dumps({"target_company": "Globex", "heading": {}, "skills": {}}))
    apply_buttons[0].click()
    at.run()

    assert not at.exception
    assert at.session_state["optimized_resume_data"]["target_company"] == "Globex"
    assert at.session_state["tracked_application_id"] is None


def test_download_caption_reflects_not_yet_recorded():
    """Finding 5: before the first download, the caption under the Download
    button must say what the upcoming click will actually do."""
    at = run_app(
        active_view="Generator",
        logged_in=True,
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Acme_Role_Resume.pdf"},
    )
    captions = [c.value for c in at.caption]
    assert "Downloading records this application in the tracker." in captions
    assert not any("Already recorded" in c for c in captions)


def test_download_caption_reflects_already_recorded():
    """Finding 5: once tracked_application_id is set, the caption must stop
    claiming the next click will record it — should_record_application()
    guarantees it deliberately won't (that guard is the whole point of this
    branch's dedupe mechanism), and the pre-fix copy claimed otherwise."""
    at = run_app(
        active_view="Generator",
        logged_in=True,
        tracked_application_id="Acme",
        optimized_resume_data={"target_company": "Acme"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Acme_Role_Resume.pdf"},
    )
    captions = [c.value for c in at.caption]
    assert "Already recorded in the tracker. Downloading again will not add another row." in captions
    assert not any(c == "Downloading records this application in the tracker." for c in captions)
