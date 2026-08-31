"""Word (.docx) export, built straight from the resume JSON.

Outside app.py for the same reason workspace.py is: app.py is a top-level
Streamlit script, so importing it executes the entire UI and nothing defined in
it can be tested in place. Nothing here imports streamlit.

This deliberately does NOT try to reproduce the LaTeX templates. main.tex and
elsa_main.tex are the typeset artefact; this is the editable one - for the
recruiter who asks for "your CV in Word", or the application portal that only
accepts .docx. Chasing two templates that keep changing, in a library with no
concept of their layout, would be a race this file could only lose, and the
result would be a worse PDF rather than a useful Word file.

History: this existed once (commit 21ef9ce "word_export", 2026-04-09) and was
deleted piecemeal - the function in 929225c, then python-docx from
requirements.txt in d7354f7, both commits titled "fix" and neither about Word.
The old implementation also had a silent bug this one does not: its default
block order listed "Projects & Patents" but the loop had no branch for it, so
projects and patents were dropped from every file it produced.
"""
import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.shared import Inches, Pt

# Matches app.py's BLOCK_ORDER_OPTIONS. Not imported from there - see the module
# docstring - so build_resume_docx() takes the order as a required argument
# instead of keeping a second copy that can drift out of sync with the
# multiselect the user actually sets.
SUMMARY = "Summary"
EXPERIENCE = "Experience"
EDUCATION = "Education"
PROJECTS_AND_PATENTS = "Projects & Patents"
SKILLS = "Skills"


def _as_list(value):
    """A section's entries, whatever shape the JSON actually holds.

    A bare string here is the dangerous case, not the missing one: `for entry
    in "Cambridge"` iterates CHARACTER BY CHARACTER and silently explodes one
    entry into eleven empty ones. app.py's details_to_text() carries the same
    guard for the same reason - ai.rewrite_resume() does not validate element
    shapes, and the three manual-import paths accept arbitrary pasted JSON.
    """
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return value
    return []


def _as_entry(item, primary_field):
    """One entry as a dict, mapping a bare string onto its headline field.

    tests/test_draft_table.py has dedicated regression tests for education and
    projects arriving as lists of plain strings, so this is a shape the app
    already promises to survive, not a hypothetical.
    """
    if isinstance(item, dict):
        return item
    text = str(item or "").strip()
    return {primary_field: text} if text else {}


def _text(value):
    """A field as a trimmed string, tolerating None and non-strings alike."""
    if value is None:
        return ""
    return str(value).strip()


def _add_heading(doc, text):
    """Section heading.

    A styled paragraph rather than doc.add_heading(): Word's built-in Heading 1
    is blue, oversized and carries an outline level, which reads as a chapter
    title in what is meant to be a one-page CV. This is just bold small caps
    with a rule under it, which is what the LaTeX templates do too.
    """
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(10)
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(11)
    return paragraph


def _add_entry(doc, left, right):
    """One "Company — Role" style line, with its date/location pushed right.

    Word has no float, so the right-hand text is appended after a tab and the
    paragraph carries a right-aligned tab stop at the text width. Without the
    explicit stop the tab lands on Word's 0.5" default grid and the dates end
    up ragged.
    """
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(0)
    if right:
        paragraph.paragraph_format.tab_stops.add_tab_stop(
            Inches(7.5), WD_TAB_ALIGNMENT.RIGHT
        )
    run = paragraph.add_run(left)
    run.bold = True
    if right:
        paragraph.add_run("\t" + right)
    return paragraph


def _add_bullets(doc, lines):
    for line in lines:
        text = (line or "").strip()
        if not text:
            continue
        bullet = doc.add_paragraph(text, style="List Bullet")
        bullet.paragraph_format.space_after = Pt(0)


def _new_document():
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)
    return doc


def _add_letterhead(doc, resume_data):
    heading = resume_data.get("heading")
    heading = heading if isinstance(heading, dict) else {}

    name = doc.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name.paragraph_format.space_after = Pt(2)
    run = name.add_run(_text(heading.get("name")))
    run.bold = True
    run.font.size = Pt(20)

    contact = [
        _text(heading.get(field))
        for field in ("email", "phone", "linkedin", "website")
    ]
    contact = [item for item in contact if item]
    if contact:
        line = doc.add_paragraph(" | ".join(contact))
        line.alignment = WD_ALIGN_PARAGRAPH.CENTER
        line.paragraph_format.space_after = Pt(2)


def _render_summary(doc, resume_data):
    text = _text(resume_data.get("summary"))
    if not text:
        return
    _add_heading(doc, SUMMARY)
    doc.add_paragraph(text)


def _bullet_lines(details):
    """Bullet texts from an entry's "details", in any of its observed shapes.

    Mirrors app.py's details_to_text(): an already-joined string is one bullet,
    not one bullet per character.
    """
    if isinstance(details, str):
        text = details.strip()
        return [text] if text else []
    lines = []
    for detail in _as_list(details):
        if isinstance(detail, dict):
            lines.append(_text(detail.get("description")))
        else:
            lines.append(_text(detail))
    return lines


def _render_experience(doc, resume_data):
    entries = _as_list(resume_data.get("experience"))
    if not entries:
        return
    _add_heading(doc, "Work Experience")
    for entry in entries:
        entry = _as_entry(entry, "company")
        left = " — ".join(
            part for part in (_text(entry.get("company")), _text(entry.get("role"))) if part
        )
        right = " · ".join(
            part for part in (_text(entry.get("time_duration")),
                              _text(entry.get("company_location"))) if part
        )
        _add_entry(doc, left, right)
        _add_bullets(doc, _bullet_lines(entry.get("details")))


def _render_education(doc, resume_data):
    entries = _as_list(resume_data.get("education"))
    if not entries:
        return
    _add_heading(doc, EDUCATION)
    for entry in entries:
        entry = _as_entry(entry, "school")
        left = " — ".join(
            part for part in (_text(entry.get("school")), _text(entry.get("degree"))) if part
        )
        right = " · ".join(
            part for part in (_text(entry.get("time_period")),
                              _text(entry.get("school_location"))) if part
        )
        _add_entry(doc, left, right)


def _render_projects_and_patents(doc, resume_data):
    """The section the deleted implementation listed but never rendered.

    Projects and patents share one heading because they share one block in the
    export-order control the user actually sets; splitting them here would make
    the Word file disagree with the PDF about how many sections exist.
    """
    rows = [
        *(("project", item) for item in _as_list(resume_data.get("projects"))),
        *(("patent", item) for item in _as_list(resume_data.get("patents"))),
    ]
    if not rows:
        return
    _add_heading(doc, PROJECTS_AND_PATENTS)
    for kind, item in rows:
        item = _as_entry(item, "name")
        name = _text(item.get("name"))
        if kind == "patent" and name:
            name = f"{name} (patent)"
        _add_entry(doc, name, _text(item.get("time")))
        description = _text(item.get("description"))
        if description:
            body = doc.add_paragraph(description)
            body.paragraph_format.space_after = Pt(0)


def _render_skills(doc, resume_data):
    skills = resume_data.get("skills")
    skills = skills if isinstance(skills, dict) else {}
    # Sorted rather than the old hard-coded set1/set2/set3: the profile editor
    # lets a user add set4 and beyond, and the old loop silently dropped them.
    groups = []
    for key in sorted(skills, key=str):
        value = skills.get(key)
        if not isinstance(value, dict):
            continue
        items = value.get("items")
        # Mirrors app.py's skills handling: an already-joined string is used
        # as-is rather than re-joined character by character.
        text = items.strip() if isinstance(items, str) else ", ".join(
            _text(item) for item in _as_list(items) if _text(item)
        )
        if text:
            groups.append((_text(value.get("title")), text))
    if not groups:
        return
    _add_heading(doc, SKILLS)
    for title, text in groups:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(0)
        if title:
            paragraph.add_run(f"{title}: ").bold = True
        paragraph.add_run(text)


_RENDERERS = {
    SUMMARY: _render_summary,
    EXPERIENCE: _render_experience,
    EDUCATION: _render_education,
    PROJECTS_AND_PATENTS: _render_projects_and_patents,
    SKILLS: _render_skills,
}


def build_resume_docx(resume_data, block_order):
    """The resume as an editable .docx. Returns bytes.

    `block_order` is the same list of section names the Export Settings
    multiselect produces, and is required rather than defaulted so this module
    cannot hold a second, drifting copy of that order. Unknown names are
    ignored, so a future block added to the PDF path shows up here as a missing
    section instead of a crash.
    """
    resume_data = resume_data if isinstance(resume_data, dict) else {}
    doc = _new_document()
    _add_letterhead(doc, resume_data)
    for block in _as_list(block_order):
        renderer = _RENDERERS.get(block)
        if renderer:
            renderer(doc, resume_data)
    return _to_bytes(doc)


def build_cover_letter_docx(resume_data):
    """The cover letter as an editable .docx, or None when there is no letter.

    Returning None for empty mirrors generate_cover_letter_pdf_bytes() in
    app.py, so the caller needs no new branch to decide whether a download
    button should exist.
    """
    resume_data = resume_data if isinstance(resume_data, dict) else {}
    body = _text(resume_data.get("cover_letter"))
    if not body:
        return None

    doc = _new_document()
    _add_letterhead(doc, resume_data)
    for block in body.split("\n\n"):
        block = block.strip()
        if block:
            doc.add_paragraph(block)
    return _to_bytes(doc)


def _to_bytes(doc):
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
