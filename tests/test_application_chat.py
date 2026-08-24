"""Coverage for the "Ask about this application" Q&A box.

Split across the two halves the feature is built from, and the split matters:

- ai.build_application_chat_prompt() is where the feature actually lives. The
  grounding rules are the product - a chat box that invents a metric puts a lie
  on a job application under the user's own name - so they get asserted
  directly, without a network call, the same way build_screening_prompt() and
  build_rewrite_prompt() are testable on their own.
- app.py's render_application_chat() only moves text between session_state and
  chat bubbles. What is worth pinning there is the wiring: where it renders,
  what happens with no API key, that a failure is still recorded, and that the
  transcript is dropped when the application changes.

Nothing here calls Gemini. The one test that needs an answer monkeypatches
ai.answer_application_question, which works because app.py does `import ai` and
calls through the module, so AppTest's in-process run sees the patched
attribute.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import ai

# Same anchoring rationale as the other test files: AppTest.from_file resolves
# a relative path against this file's directory, not the process cwd.
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


PROFILE = {
    "heading": {"name": "Ada Lovelace"},
    "experience": [{"company": "Analytical Engines Ltd", "role": "Engineer"}],
}
OPTIMIZED = {"target_company": "Globex", "summary": "Rewritten for Globex."}


# ---------------------------------------------------------------------------
# The prompt - i.e. the feature
# ---------------------------------------------------------------------------

def test_prompt_carries_every_grounding_source():
    """Profile, optimized result, JD and transcript all have to reach the model.

    "AI 記住我所有這次生成以及我的個人資料" is the whole requirement; if any one
    of these is dropped the answers stop being grounded in the user's own data
    and start being plausible fiction.
    """
    prompt = ai.build_application_chat_prompt(
        [{"role": "user", "content": "Why do you want to work here?"}],
        "Globex is hiring a Staff Engineer.",
        PROFILE,
        OPTIMIZED,
    )
    assert "Ada Lovelace" in prompt
    assert "Analytical Engines Ltd" in prompt
    assert "Rewritten for Globex." in prompt
    assert "Globex is hiring a Staff Engineer." in prompt
    assert "Why do you want to work here?" in prompt


def test_prompt_forbids_inventing_facts():
    """The load-bearing rule, pinned verbatim-ish.

    Everything else in this feature is plumbing that can be rewritten freely.
    This cannot: an application answer containing a fabricated metric is not a
    quality regression, it is a false statement submitted under the candidate's
    name, and they will not discover it until an interviewer asks about the
    number. If a future prompt edit softens this, this test should fail.
    """
    prompt = ai.build_application_chat_prompt([], "", PROFILE, OPTIMIZED)
    assert "DO NOT invent it" in prompt
    assert "Never" in prompt and "invent an employer" in prompt
    # The recovery matters as much as the prohibition - refusing silently would
    # be useless. It has to name what is missing and ask for it.
    assert "ask the candidate for it" in prompt


def test_prompt_names_the_missing_optimized_result_instead_of_leaving_a_hole():
    """A blank section invites the model to assume the resume failed to load;
    saying "none yet" tells it this is a normal state to work around. The box
    renders before the first Optimize run, so this is the common case, not an
    edge case."""
    prompt = ai.build_application_chat_prompt([], "JD here", PROFILE, None)
    assert "none yet" in prompt
    assert "has not run an optimization" in prompt


def test_prompt_keeps_only_the_most_recent_turns():
    """Bounds cost and latency on a long session. Safe to trim because the
    resume and JD - what answers are actually built from - are resent in full
    every turn regardless; only old chatter is dropped."""
    messages = [
        {"role": "user", "content": f"question-{i}"}
        for i in range(ai.MAX_CHAT_HISTORY + 5)
    ]
    prompt = ai.build_application_chat_prompt(messages, "", PROFILE, OPTIMIZED)
    assert "question-0" not in prompt
    assert f"question-{ai.MAX_CHAT_HISTORY + 4}" in prompt


def test_answer_reports_a_missing_key_instead_of_calling_gemini():
    ok, message = ai.answer_application_question([], "", PROFILE, OPTIMIZED, "")
    assert ok is False
    assert "API key" in message


# ---------------------------------------------------------------------------
# Where it renders
# ---------------------------------------------------------------------------

def test_chat_renders_on_generator_before_any_optimization():
    """Deliberately not gated on optimized_resume_data. The profile and the JD
    alone already answer plenty of what an application form asks, and gating it
    would hide the box exactly when a first-time user is looking for help."""
    at = run_app(active_view="Generator")
    assert not at.exception
    assert len(at.chat_input) == 1


def test_chat_absent_outside_generator():
    """The owner asked for it on the generate/adjust side. It is scoped to
    render_generator_workspace(), so Profile and Tracker must not grow one."""
    for view in ("Profile", "Tracker"):
        at = run_app(active_view=view)
        assert not at.exception
        assert at.chat_input.len == 0, view


def test_chat_input_disabled_without_an_api_key():
    """Every answer is a Gemini round trip, so an enabled box with no key just
    invites the user to type a paragraph and get an error."""
    at = run_app(active_view="Generator", api_key="")
    assert not at.exception
    assert at.chat_input[0].disabled is True

    at = run_app(active_view="Generator", api_key="fake-key")
    assert not at.exception
    assert at.chat_input[0].disabled is False


# ---------------------------------------------------------------------------
# One turn
# ---------------------------------------------------------------------------

def test_asking_a_question_records_both_sides(monkeypatch):
    captured = {}

    def fake_answer(messages, jd_text, resume_data, optimized_resume, api_key):
        captured["messages"] = list(messages)
        captured["jd_text"] = jd_text
        captured["optimized_resume"] = optimized_resume
        return True, "Because Globex works on analytical engines."

    monkeypatch.setattr(ai, "answer_application_question", fake_answer)

    at = run_app(
        active_view="Generator",
        api_key="fake-key",
        jd_text="Globex is hiring.",
        resume_data=PROFILE,
        optimized_resume_data=OPTIMIZED,
    )
    at.chat_input[0].set_value("Why Globex?").run()
    assert not at.exception

    transcript = at.session_state["application_chat"]
    assert [m["role"] for m in transcript] == ["user", "assistant"]
    assert transcript[0]["content"] == "Why Globex?"
    assert transcript[1]["content"] == "Because Globex works on analytical engines."

    # The question just asked has to be inside the transcript handed to ai.py -
    # build_application_chat_prompt()'s docstring says it expects that, and
    # passing the history *without* it would ask the model to answer nothing.
    assert captured["messages"][-1] == {"role": "user", "content": "Why Globex?"}
    assert captured["jd_text"] == "Globex is hiring."
    assert captured["optimized_resume"] == OPTIMIZED


def test_a_failed_answer_stays_in_the_transcript(monkeypatch):
    """Rendering the error into the bubble is not enough on its own: the next
    rerun redraws the transcript from session_state, so an unrecorded failure
    evaporates and leaves the user looking at their own unanswered question
    with no record of what went wrong."""
    monkeypatch.setattr(
        ai,
        "answer_application_question",
        lambda *a, **k: (False, "429 quota exceeded"),
    )
    at = run_app(active_view="Generator", api_key="fake-key", resume_data=PROFILE)
    at.chat_input[0].set_value("Why Globex?").run()
    assert not at.exception

    transcript = at.session_state["application_chat"]
    assert len(transcript) == 2
    assert transcript[1]["role"] == "assistant"
    assert "429 quota exceeded" in transcript[1]["content"]


# ---------------------------------------------------------------------------
# Lifetime
# ---------------------------------------------------------------------------

def test_transcript_is_dropped_when_the_application_changes():
    """One optimize run is one application - the rule tracked_application_id
    already follows. A transcript about the Acme role must not follow the user
    into the Globex one, where every answer it already gave is now subtly wrong
    while still looking authoritative.

    Driven through the profile's Advanced JSON Import button for the same
    reason test_tracker_guard.py drives clear_generated_outputs() through it: it
    is the one caller that needs neither a live Gemini key nor network access,
    so the test stays hermetic.

    show_advanced_tools=True is required only because that box is still behind
    the sidebar checkbox on this branch. Commit b6202be ("fux", currently on
    fix/render-all-pages and NOT merged into main - PR #11 stopped at fbc7a72)
    deletes the checkbox and renders the box unconditionally. When that lands,
    drop this override here, the same way that commit already drops it from
    test_tracker_guard.py and test_draft_table.py.
    """
    at = run_app(
        active_view="Profile",
        show_advanced_tools=True,
        application_chat=[{"role": "user", "content": "about the Acme role"}],
    )
    assert at.session_state["application_chat"]

    editors = [t for t in at.text_area if t.key.startswith("base_json_import_")]
    assert len(editors) == 1
    editors[0].set_value('{"heading": {"name": "Ada"}}')
    apply_buttons = [b for b in at.button if b.label == "Apply JSON Import"]
    assert len(apply_buttons) == 1
    apply_buttons[0].click().run()
    assert not at.exception

    assert at.session_state["application_chat"] == []
