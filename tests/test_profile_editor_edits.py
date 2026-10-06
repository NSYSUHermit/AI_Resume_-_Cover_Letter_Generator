"""Regression: the second consecutive edit to the same Profile field must not
be thrown away.

Reported as "the first thing I type disappears, the second time it sticks".
Mechanism under test: render_resume_form_editor() passes `value=<current
data>` alongside `key=`. Streamlit folds the default into the widget identity,
so once an edit is written back into resume_data the field's default changes,
the widget becomes a *new* widget, and the client state carrying the user's
NEXT edit (sent under the old identity) is dropped in favour of the default.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception
    return at


def name_key(at):
    return f"base_form_{at.session_state['base_editor_key']}_name"


def test_two_consecutive_edits_to_the_same_field_both_stick():
    at = run_app(active_view="Profile")

    at.text_input(key=name_key(at)).input("Henry").run()
    assert not at.exception
    assert at.session_state["resume_data"]["heading"]["name"] == "Henry"

    # Second edit, right after the first one was written back.
    at.text_input(key=name_key(at)).input("Henry Lin").run()
    assert not at.exception
    assert at.session_state["resume_data"]["heading"]["name"] == "Henry Lin"
    assert at.text_input(key=name_key(at)).value == "Henry Lin"


def test_edit_survives_a_rerun_caused_by_another_field():
    at = run_app(active_view="Profile")
    at.text_input(key=name_key(at)).input("Henry").run()
    email_key = name_key(at).replace("_name", "_email")
    at.text_input(key=email_key).input("henry@example.com").run()
    assert not at.exception
    heading = at.session_state["resume_data"]["heading"]
    assert heading == {**heading, "name": "Henry", "email": "henry@example.com"}


# --- data_editor identity -----------------------------------------------------
# AppTest cannot replay the real failure for tables: it presets edits through
# st.session_state[<key>], which Streamlit re-binds to whatever widget the key
# resolves to, whereas the browser sends edits under the widget's *element id*.
# So the test pins the mechanism instead: the element id of a profile table must
# not change on the rerun after an edit has been written back into resume_data.
# streamlit 1.61.1 (elements/widgets/data_editor.py) folds the full data into
# the id for num_rows="dynamic" editors, so a seed rebuilt from the edited
# resume_data produces a new id - and the user's next edit, sent under the old
# id, is silently dropped. That is the reported "first input disappears".
def education_editor_id(at):
    key = f"base_form_{at.session_state['base_editor_key']}_education"
    ids = [e.proto.id for e in at.dataframe if e.proto.id.endswith(key)]
    assert len(ids) == 1, [e.proto.id for e in at.dataframe]
    return ids[0]


def test_profile_table_identity_is_stable_across_an_edit():
    at = run_app(active_view="Profile")
    key = f"base_form_{at.session_state['base_editor_key']}_education"
    before = education_editor_id(at)

    at.session_state[key] = {
        "edited_rows": {0: {"school": "NSYSU", "degree": "M.S."}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert at.session_state["resume_data"]["education"][0]["school"] == "NSYSU"
    assert education_editor_id(at) == before

    # The rerun AFTER the write-back is where the id used to change. AppTest
    # does not carry data_editor state between runs on its own (Dataframe is
    # not a Widget in its element tree), so the browser's resend of the same
    # edit log is simulated by presetting it again.
    at.session_state[key] = {
        "edited_rows": {0: {"school": "NSYSU", "degree": "M.S."}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert education_editor_id(at) == before
    assert at.session_state["resume_data"]["education"][0]["school"] == "NSYSU"
