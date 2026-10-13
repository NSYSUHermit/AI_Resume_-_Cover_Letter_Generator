"""Layout of the Generator's left column (render_generator_workspace()).

- No "Source of Truth" card. Users did not understand the name, and it only
  repeated what the sidebar's Career Profile button and the preview's own
  empty state already say.
- "Ask about this application" is the last thing in the column. Users rarely
  use it, so it no longer sits between the optimize step and the export step.

Order is read from AppTest's element tree: iterating a Block walks it depth
first in render order, so an element's position in that walk is its position
on the page.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"

PROFILE = {
    "heading": {"name": "Ada", "email": "", "phone": "", "website": "", "linkedin": ""},
    "summary": "Engineer.",
    "education": [],
    "experience": [{"company": "Acme", "role": "Engineer", "time_duration": "2020",
                    "company_location": "", "details": [{"description": "Did things"}]}],
    "projects": [],
    "patents": [],
    "skills": {"set1": {"title": "Skills", "items": ["Python"]}},
    "cover_letter": "",
}


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception
    return at


def position(at, predicate):
    """Index of the first node in render order matching `predicate`."""
    for i, node in enumerate(at.main):
        if predicate(node):
            return i
    raise AssertionError("no matching element")


def is_chat(node):
    return node.type == "expander" and node.label == "Ask about this application"


def test_source_of_truth_card_is_gone():
    for resume in (None, PROFILE):
        overrides = {"active_view": "Generator"}
        if resume:
            overrides["resume_data"] = resume
        at = run_app(**overrides)
        assert "Source of Truth" not in [h.value for h in at.subheader]
        assert "Edit Career Profile" not in [b.label for b in at.button]


def test_chat_comes_after_export_settings():
    at = run_app(active_view="Generator")
    export = position(at, lambda n: n.type == "subheader" and n.value == "Export Settings")
    ats_hint = position(
        at, lambda n: n.type == "caption" and n.value.startswith("Optimize a resume to see how it scores"),
    )
    assert position(at, is_chat) > max(export, ats_hint)


def test_chat_comes_after_the_ats_analysis():
    at = run_app(
        active_view="Generator",
        resume_data=PROFILE,
        optimized_resume_data=PROFILE,
        changelog="Tightened the summary.",
    )
    changelog = position(at, lambda n: n.type == "markdown" and "Optimization Changelog" in n.value)
    assert position(at, is_chat) > changelog
