"""Coverage for the redesigned sidebar (brand block, recent-applications
list, bottom account block) layered on top of the existing three-view nav.

The one piece of this with a real cost trap is render_sidebar_recent_
applications() (app.py): it needs Firestore data, but the sidebar renders on
every rerun of every view. Naively fetching there would mean a Firestore
read per rerun, times every view, times every signed-in user. The tests
below prove that does not happen - see report.md for the full design.

Firestore is faked at the same seam test_tracker_guard.py already uses:
monkeypatching firebase_dashboard.init_firebase, a normally-imported
module-level function, rather than anything defined inside app.py - see that
file's own module docstring for why AppTest re-executing the whole script on
every .run() makes that patch point work (app.py's own
`from firebase_dashboard import ...` line re-binds to the patched function on
every run, not just the first).

Deliberately not mocking firebase_dashboard.fetch_applications() itself: the
sidebar calls it unconditionally whenever the user is logged in, on every
rerun, by design - fetch_applications() is the caching layer, and it is the
one deciding whether that call actually reaches Firestore. Counting calls to
fetch_applications() would therefore just show "called once per rerun" no
matter what, and prove nothing about caching. What has to be counted is the
one call inside fetch_applications() that stands in for a real network
round-trip: db.collection(...).stream().
"""
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

# Same anchoring rationale as test_app_smoke.py / test_tracker_guard.py:
# AppTest.from_file() resolves a relative path against this file's own
# directory, not the process cwd.
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


class _FakeFirestoreNode:
    """Stand-in for the db.collection(...).document(...).collection(...)
    .order_by(...).stream() chain firebase_dashboard.fetch_applications()
    calls. Every method but stream() just returns self - the exact shape of
    the chain does not need modelling, only that .stream() is the one call a
    real network round-trip would sit behind, which makes it the one call
    worth counting."""

    def __init__(self, docs, calls):
        self._docs = docs
        self._calls = calls

    def collection(self, *a, **k):
        return self

    def document(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def stream(self):
        self._calls.append(1)
        return list(self._docs)


class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


def _fake_db(records):
    """A fake Firestore client, plus the list it appends to on every real
    .stream() call - the "was Firestore actually hit" signal these tests
    check instead of trusting fetch_applications() to behave."""
    calls = []
    docs = [_FakeDoc(f"doc{i}", data) for i, data in enumerate(records)]
    return _FakeFirestoreNode(docs, calls), calls


def test_logged_out_sidebar_never_calls_firestore(monkeypatch):
    """omit the whole section" requirement: a signed-out visitor must never
    cause a Firestore read, not even a first one."""
    fake_db, calls = _fake_db([{"company_name": "Acme", "status": "Applied"}])
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: fake_db)

    at = run_app(logged_in=False)

    assert not at.exception
    assert calls == []


def test_logged_in_second_rerun_does_not_repeat_the_fetch(monkeypatch):
    """The other half: a signed-in session's sidebar must hit Firestore once,
    not once per rerun. fetch_applications()'s own session_state cache is
    what is under test here - this only proves the sidebar's use of it does
    not defeat it (e.g. by passing a different cache key each time, or by
    forcing a refresh it has no reason to force)."""
    fake_db, calls = _fake_db([
        {
            "company_name": "Acme",
            "status": "Applied",
            "resume_json": {"target_role": "Backend Engineer"},
        },
    ])
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: fake_db)

    at = run_app(logged_in=True, user_email="test@example.com")
    assert not at.exception
    assert calls == [1]  # first render: exactly one real fetch

    at.run()  # a second rerun, nothing new staged - e.g. any other widget touch
    assert not at.exception
    assert calls == [1]  # still one - fetch_applications()'s cache held


def test_recent_applications_rows_render_from_the_fetched_records(monkeypatch):
    """Companion to the call-count tests above: confirms the cached fetch
    actually reaches the screen as rows, not just that it is cheap. Two
    records in, two rows out (both under the limit of three), newest-first
    order preserved from fetch_applications()."""
    fake_db, calls = _fake_db([
        {"company_name": "Acme", "status": "Applied", "resume_json": {"target_role": "Backend Engineer"}},
        {"company_name": "Globex", "status": "Offered", "resume_json": {"target_role": "PM"}},
    ])
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: fake_db)

    at = run_app(logged_in=True, user_email="test@example.com")
    assert not at.exception
    assert calls == [1]

    row_labels = [b.label for b in at.sidebar.button if b.key and b.key.startswith("recent_app_")]
    assert row_labels == ["Acme — Backend Engineer", "Globex — PM"]


def test_clicking_a_recent_application_row_switches_to_tracker(monkeypatch):
    fake_db, _calls = _fake_db([
        {"company_name": "Acme", "status": "Applied", "resume_json": {"target_role": "Backend Engineer"}},
    ])
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: fake_db)

    at = run_app(logged_in=True, user_email="test@example.com", active_view="Profile")
    row_buttons = [b for b in at.sidebar.button if b.key and b.key.startswith("recent_app_")]
    assert len(row_buttons) == 1

    row_buttons[0].click().run()
    assert not at.exception
    assert at.session_state["active_view"] == "Tracker"


def test_recording_a_new_application_invalidates_the_recent_list_cache(monkeypatch):
    """"Invalidate when a new application is recorded" requirement:
    sync_application_to_tracker() (app.py) is where a record gets written.
    Its real save_application() call (firebase_dashboard.py) already sets
    force_refresh_apps=True on a successful write; the fake below mirrors
    just that one side effect (same monkeypatch shape as test_tracker_guard.
    py's test_successful_write_sets_flag_and_survives_the_rerun) so this can
    drive an actual download through the real code path and confirm the
    sidebar's own fetch honours the flag on the next rerun, instead of
    silently replaying the pre-download list.

    Confirmed empirically that this needs no extra .run() of its own beyond
    the click: sync_application_to_tracker() ends with an app-scope
    st.rerun() on a successful write (see that function's own comment on
    why - the "Saved to tracker" progress row lives outside render_preview's
    @st.fragment and would not otherwise update). AppTest's .run() drives the
    script until it stabilises, so that internal rerun already re-executes
    the sidebar - with the now-True force_refresh_apps flag - inside this
    same .click().run() call, one script pass after the one that set the
    flag (`with st.sidebar:` renders near the top of app.py, well before the
    Generator view's download button further down, so the sidebar's own
    fetch in *that* first pass still ran from the cache that was valid at
    the time).
    """
    fake_db, calls = _fake_db([
        {"company_name": "Acme", "status": "Applied", "resume_json": {}},
    ])
    monkeypatch.setattr("firebase_dashboard.init_firebase", lambda: fake_db)

    def fake_save_application(db, email, company_name, resume_json, jd_text=""):
        st.session_state.force_refresh_apps = True
        return True

    monkeypatch.setattr("firebase_dashboard.save_application", fake_save_application)

    at = run_app(
        active_view="Generator",
        logged_in=True,
        user_email="test@example.com",
        optimized_resume_data={"target_company": "Globex"},
        resume_preview_bytes=b"%PDF-fake",
        resume_dl_data={"bytes": b"%PDF-fake", "name": "Globex_Role_Resume.pdf"},
    )
    assert not at.exception
    assert calls == [1]  # sidebar's own first-render fetch

    at.download_button[0].click().run()
    assert not at.exception
    assert at.session_state["tracked_application_id"] == "Globex"
    # The download recorded the application (force_refresh_apps flipped) and
    # AppTest's .run() already carried the resulting app-scope rerun through
    # to completion, so the sidebar re-fetched within this same call.
    assert calls == [1, 1]

    at.run()  # one more, uneventful rerun
    assert not at.exception
    assert calls == [1, 1]  # force_refresh_apps was consumed - back to cached


def test_sidebar_still_exposes_exactly_three_nav_buttons():
    """The redesign must not disturb the nav contract other tests
    (test_app_smoke.py) pin: same three keys, same order."""
    at = run_app()
    nav_keys = [b.key for b in at.sidebar.button if b.key and b.key.startswith("nav_")]
    assert nav_keys == ["nav_Profile", "nav_Generator", "nav_Tracker"]


def test_login_form_is_not_inside_the_settings_expander():
    """Signed-out users need the login/register form directly visible, not
    behind a click - it must sit outside the "Settings" expander."""
    at = run_app(logged_in=False)
    assert not at.exception

    settings_expanders = [e for e in at.sidebar.expander if e.label == "Settings"]
    assert len(settings_expanders) == 1
    settings = settings_expanders[0]

    # Block.__iter__ (streamlit.testing.v1.element_tree) recurses into every
    # descendant, so settings.text_input only finds widgets actually nested
    # inside this expander - it is not scoped by proximity or DOM order.
    assert len(settings.text_input) == 0
    # The email + password inputs still exist somewhere else in the sidebar.
    assert len(at.sidebar.text_input) == 2
