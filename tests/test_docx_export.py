"""Coverage for docx_export.py — the Word export, restored.

This module is pure (JSON in, bytes out, no streamlit), so unlike most of this
repo's UI coverage these tests read the produced document back and assert on its
actual text rather than on a source string. python-docx can reopen its own
output, so "did the projects section survive" is a real question here, not one
AppTest has to be talked around.

Two themes dominate, and both come from the history in docx_export.py's own
docstring:

- The deleted implementation listed "Projects & Patents" in its default block
  order and had no branch for it, so those sections vanished from every file it
  ever produced. Several tests below exist purely so that cannot recur.
- Resume JSON in this app is not schema-validated. ai.rewrite_resume() does not
  check element shapes and three manual-import paths accept arbitrary pasted
  JSON, so entries arrive as bare strings, "details" arrives pre-joined, and
  skills sets go past set3. tests/test_draft_table.py already guards the UI
  against those shapes; the exporter needs the same treatment or the download
  button becomes a crash.
"""
import io

import pytest
from docx import Document

import docx_export

ALL_BLOCKS = ["Summary", "Experience", "Education", "Projects & Patents", "Skills"]

FULL = {
    "heading": {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "0912-345-678",
        "linkedin": "in/ada",
    },
    "summary": "Analytical engine specialist.",
    "experience": [{
        "company": "Analytical Engines Ltd",
        "role": "Lead Engineer",
        "time_duration": "2020-2024",
        "company_location": "London",
        "details": [{"description": "Wrote the first published algorithm."}],
    }],
    "education": [{
        "school": "Cambridge",
        "degree": "BSc Mathematics",
        "time_period": "2016-2020",
        "school_location": "UK",
    }],
    "projects": [{"name": "Note G", "time": "1843", "description": "Bernoulli numbers."}],
    "patents": [{"name": "Punch card feeder", "time": "1844", "description": "Mechanism."}],
    "skills": {"set1": {"title": "Languages", "items": ["Python", "Ada"]}},
    "cover_letter": "Dear hiring manager,\n\nI would like to apply.\n\nSincerely,\nAda",
}


def text_of(blob):
    """Every paragraph of a .docx, joined - i.e. what a reader would see."""
    return "\n".join(p.text for p in Document(io.BytesIO(blob)).paragraphs)


# ---------------------------------------------------------------------------
# Content survives the round trip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected", [
    "Ada Lovelace",
    "ada@example.com",
    "Analytical engine specialist.",
    "Analytical Engines Ltd",
    "Lead Engineer",
    "2020-2024",
    "Wrote the first published algorithm.",
    "Cambridge",
    "BSc Mathematics",
    "Note G",
    "Bernoulli numbers.",
    "Languages",
    "Python, Ada",
])
def test_every_field_reaches_the_document(expected):
    assert expected in text_of(docx_export.build_resume_docx(FULL, ALL_BLOCKS))


def test_projects_and_patents_are_actually_rendered():
    """The bug the deleted implementation shipped with.

    Its default block order listed "Projects & Patents" but its loop had no
    branch for that name, so the section was silently dropped from every file.
    Nothing about that failure was visible without opening the .docx and
    noticing an absence - which is exactly why it survived until deletion.
    """
    body = text_of(docx_export.build_resume_docx(FULL, ALL_BLOCKS))
    assert "PROJECTS & PATENTS" in body
    assert "Note G" in body
    # Patents are merged into the same section but stay distinguishable; a
    # patent listed as an indistinguishable "project" would misrepresent it.
    assert "Punch card feeder (patent)" in body


def test_block_order_is_obeyed_and_omissions_respected():
    """The order comes from the Export Settings multiselect, so deselecting a
    section there has to drop it here too - otherwise the Word file and the PDF
    disagree about what the resume contains."""
    body = text_of(docx_export.build_resume_docx(FULL, ["Skills", "Summary"]))
    assert body.index("SKILLS") < body.index("SUMMARY")
    assert "Analytical Engines Ltd" not in body
    assert "Cambridge" not in body


def test_unknown_block_names_are_ignored():
    """A block added to the PDF path later should show up here as a missing
    section, not as a crash on a download button."""
    blob = docx_export.build_resume_docx(FULL, ["Summary", "Publications"])
    assert "Analytical engine specialist." in text_of(blob)


# ---------------------------------------------------------------------------
# Shapes this app's JSON actually arrives in
# ---------------------------------------------------------------------------

def test_entries_may_be_bare_strings():
    """tests/test_draft_table.py guards the UI against education and projects
    arriving as lists of plain strings. The exporter sees the same data."""
    body = text_of(docx_export.build_resume_docx(
        {"education": ["Cambridge"], "projects": ["Note G"], "experience": ["Analytical Engines"]},
        ALL_BLOCKS,
    ))
    assert "Cambridge" in body
    assert "Note G" in body
    assert "Analytical Engines" in body


def test_a_section_given_as_a_string_is_not_walked_character_by_character():
    """The dangerous shape, not the missing one.

    `for entry in "Cambridge"` iterates characters, so a string where a list
    belongs silently becomes nine one-letter entries. app.py's
    details_to_text() carries the same guard for the same reason.
    """
    body = text_of(docx_export.build_resume_docx({"education": "Cambridge"}, ALL_BLOCKS))
    assert "Cambridge" in body
    assert "\nC\n" not in body


def test_details_given_as_a_joined_string_becomes_one_bullet():
    body = text_of(docx_export.build_resume_docx(
        {"experience": [{"company": "Acme", "details": "Did the thing."}]}, ALL_BLOCKS
    ))
    assert "Did the thing." in body


def test_skills_beyond_set3_are_not_dropped():
    """The old implementation looped over a hard-coded set1/set2/set3, so a
    fourth skills group entered in the profile editor never appeared."""
    body = text_of(docx_export.build_resume_docx(
        {"skills": {"set4": {"title": "Extra", "items": ["Kept"]}}}, ALL_BLOCKS
    ))
    assert "Extra" in body
    assert "Kept" in body


def test_skills_items_given_as_a_string_are_used_as_is():
    body = text_of(docx_export.build_resume_docx(
        {"skills": {"set1": {"title": "Languages", "items": "Python, Ada"}}}, ALL_BLOCKS
    ))
    assert "Python, Ada" in body


@pytest.mark.parametrize("data", [None, {}, [], "not a dict", {"heading": "not a dict"}])
def test_junk_input_still_produces_a_document(data):
    """Every one of these is reachable: optimized_resume_data is whatever was
    pasted into a manual import. A crash here would take down the whole preview
    panel, not just the download button."""
    assert docx_export.build_resume_docx(data, ALL_BLOCKS)


# ---------------------------------------------------------------------------
# Cover letter
# ---------------------------------------------------------------------------

def test_cover_letter_keeps_its_paragraphs():
    body = text_of(docx_export.build_cover_letter_docx(FULL))
    assert "Dear hiring manager," in body
    assert "I would like to apply." in body
    # The letterhead rides along, so the letter is a standalone document rather
    # than a floating block of text with no name on it.
    assert "Ada Lovelace" in body


@pytest.mark.parametrize("data", [None, {}, {"cover_letter": ""}, {"cover_letter": "   "}])
def test_no_cover_letter_returns_none(data):
    """Mirrors generate_cover_letter_pdf_bytes(), so render_preview() needs no
    new branch to decide whether the button should exist."""
    assert docx_export.build_cover_letter_docx(data) is None
