"""The post-optimize review flow (app.py render_change_review()).

After Optimize the preview on the right is the new version straight away, and
the left column lists what the AI changed and why, each with an edit box.
Edits are staged; Save & preview writes them into the optimized result and
re-renders the PDF.

Gemini is stubbed at ai.screen_job_description / ai.rewrite_resume, lualatex
at subprocess.run (same fake as tests/test_tracker_preview.py).
"""
import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"

PROFILE = {
    "heading": {"name": "Ada Review", "email": "", "phone": "", "website": "", "linkedin": ""},
    "summary": "Backend engineer.",
    "education": [],
    "experience": [{"company": "Acme", "role": "Engineer", "time_duration": "2020", "company_location": "",
                    "details": [{"description": "Built APIs in Python"}, {"description": "Ran on-call"}]}],
    "projects": [{"name": "Old Game", "time": "2019", "description": "A browser game"}],
    "patents": [],
    "skills": {"set1": {"title": "Languages", "items": ["Python"]}},
    "cover_letter": "",
}

OPTIMIZED = {
    **PROFILE,
    "target_company": "Initech",
    "target_role": "Backend Engineer",
    "summary": "Backend engineer for high-traffic APIs.",
    "experience": [{**PROFILE["experience"][0], "details": [
        {"description": "Built high-traffic REST APIs in Python"}, {"description": "Ran on-call"},
    ]}],
    "projects": [],
}

REWRITE = {
    "changelog": "Focused the resume on API work.",
    "changes": [
        {"path": "summary", "reason": "The JD asks for $1M-scale traffic."},
        {"path": "experience[0].details[0]", "reason": "REST is listed in the JD."},
        {"path": "removed:projects[0]", "reason": "Not relevant to backend work."},
    ],
    "suggested_metrics": [],
    "optimized_resume": OPTIMIZED,
}


def fake_lualatex(calls):
    class Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(cmd, cwd=None, **kwargs):
        calls.append(cmd[-1])
        with open(os.path.join(cwd, cmd[-1].replace(".tex", ".pdf")), "wb") as f:
            f.write(b"%PDF-1.4 fake " + str(len(calls)).encode())
        return Done()

    return run


def optimized_app(monkeypatch, calls=None, **state):
    """The Generator right after a successful Optimize run. `calls` records
    only the compiles from the Optimize click on - the Career Profile preview
    drawn before it is not what these tests are about."""
    calls = [] if calls is None else calls
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))
    monkeypatch.setattr(
        "ai.screen_job_description",
        lambda jd, key, **kw: {"target_company": "Initech", "target_role": "Backend Engineer", "keywords": ["REST"]},
    )
    monkeypatch.setattr("ai.rewrite_resume", lambda *a, **kw: json.loads(json.dumps(REWRITE)))
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["active_view"] = "Generator"
    at.session_state["api_key"] = "AIza-test"
    at.session_state["jd_text"] = "Initech needs a backend engineer for REST APIs. " * 3
    at.session_state["resume_data"] = json.loads(json.dumps(PROFILE))
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    calls.clear()
    [optimize] = [b for b in at.button if b.label == "Optimize Resume"]
    optimize.click().run()
    assert not at.exception
    return at


def box(at, change_id):
    prefix = f"review_{at.session_state['opt_editor_key']}_{change_id}_"
    found = [t for t in at.text_area if t.key and t.key.startswith(prefix)]
    assert len(found) == 1, [t.key for t in at.text_area]
    return found[0]


def button(at, key):
    found = [b for b in at.button if b.key == key]
    assert len(found) == 1, [b.key for b in at.button]
    return found[0]


def markdown_text(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)


# --- right after Optimize ------------------------------------------------------

def test_optimize_renders_the_new_version_into_the_preview(monkeypatch):
    calls = []
    at = optimized_app(monkeypatch, calls)
    assert calls == ["main.tex"]
    assert at.session_state["resume_preview_bytes"].startswith(b"%PDF")
    assert "3 changes to review on the left" in at.session_state["result_banner"]["details"]


def test_panel_lists_each_change_with_its_reason(monkeypatch):
    at = optimized_app(monkeypatch)
    assert "Review AI changes" in [h.value for h in at.subheader]
    text = markdown_text(at)
    assert "Focused the resume on API work" in text
    # Escaped, so "$1M" is not swallowed as the start of a maths block.
    assert r"The JD asks for \$1M\-scale traffic\." in text
    assert "REST is listed in the JD" in text
    assert "Not relevant to backend work" in text
    assert box(at, "summary").value == "Backend engineer for high-traffic APIs."
    assert box(at, "experience.0.details.0").value == "Built high-traffic REST APIs in Python"
    # The untouched bullet is not listed.
    assert not [t for t in at.text_area if t.key and "experience.0.details.1" in t.key]


# --- editing ----------------------------------------------------------------------

def test_edits_are_staged_until_save(monkeypatch):
    at = optimized_app(monkeypatch)
    box(at, "summary").input("My own summary.").run()
    assert not at.exception
    assert at.session_state["optimized_resume_data"]["summary"] == "Backend engineer for high-traffic APIs."
    assert "1 unsaved edit" in markdown_text(at)
    assert button(at, "review_save").disabled is False


def test_save_and_preview_writes_the_edits_and_rerenders(monkeypatch):
    calls = []
    at = optimized_app(monkeypatch, calls)
    before_pdf = at.session_state["resume_preview_bytes"]
    box(at, "summary").input("My own summary.").run()
    box(at, "experience.0.details.0").input("Built REST APIs").run()
    button(at, "review_save").click().run()
    assert not at.exception

    data = at.session_state["optimized_resume_data"]
    assert data["summary"] == "My own summary."
    assert data["experience"][0]["details"][0] == {"description": "Built REST APIs"}
    assert calls == ["main.tex", "main.tex"]
    assert at.session_state["resume_preview_bytes"] != before_pdf
    # Nothing left unsaved, and the boxes now show what was saved.
    assert box(at, "summary").value == "My own summary."
    assert button(at, "review_save").disabled is True


def test_use_original_stages_the_original_text(monkeypatch):
    at = optimized_app(monkeypatch)
    key = box(at, "summary").key
    button(at, f"{key}_original").click().run()
    assert not at.exception
    assert box(at, "summary").value == "Backend engineer."
    assert "1 unsaved edit" in markdown_text(at)


def test_discard_drops_staged_edits(monkeypatch):
    at = optimized_app(monkeypatch)
    box(at, "summary").input("Throwaway.").run()
    button(at, "review_discard").click().run()
    assert not at.exception
    assert box(at, "summary").value == "Backend engineer for high-traffic APIs."


def test_restoring_removed_content_on_save(monkeypatch):
    at = optimized_app(monkeypatch)
    restore = [b for b in at.button if b.key and b.key.startswith("review_restore_") and "projects.0" in b.key]
    assert len(restore) == 1 and restore[0].label == "Restore it"
    restore[0].click().run()
    assert "1 unsaved edit" in markdown_text(at)
    button(at, "review_save").click().run()
    assert not at.exception
    assert [p["name"] for p in at.session_state["optimized_resume_data"]["projects"]] == ["Old Game"]


def test_unsaved_edits_survive_a_trip_to_another_view(monkeypatch):
    at = optimized_app(monkeypatch)
    box(at, "summary").input("Half-finished thought").run()
    at.sidebar.button(key="nav_Profile").click().run()
    at.sidebar.button(key="nav_Generator").click().run()
    assert not at.exception
    assert box(at, "summary").value == "Half-finished thought"


def test_an_edit_made_elsewhere_reseeds_the_box(monkeypatch):
    """Draft Table / Edit Optimized JSON change the data directly; the review
    box must show that, not hold on to (and later save back) the old text."""
    at = optimized_app(monkeypatch)
    data = json.loads(json.dumps(at.session_state["optimized_resume_data"]))
    data["summary"] = "Edited in the Draft Table."
    at.session_state["optimized_resume_data"] = data
    at.run()
    assert box(at, "summary").value == "Edited in the Draft Table."


def test_saving_a_stale_result_keeps_the_edits_but_offers_no_pdf(monkeypatch):
    """Same rule as Generate PDF: no downloadable PDF from a result that no
    longer matches the Career Profile. The preview still shows the edited
    version (a cached render), just nothing to download."""
    at = optimized_app(monkeypatch)
    profile = json.loads(json.dumps(PROFILE))
    profile["summary"] = "Profile changed after optimizing."
    at.session_state["resume_data"] = profile
    at.run()
    box(at, "summary").input("Edited anyway.").run()
    button(at, "review_save").click().run()
    assert not at.exception
    assert at.session_state["optimized_resume_data"]["summary"] == "Edited anyway."
    assert at.session_state["resume_preview_bytes"] is None
    assert at.session_state["resume_dl_data"] is None


def test_new_optimize_run_starts_the_review_fresh(monkeypatch):
    at = optimized_app(monkeypatch)
    box(at, "summary").input("Unsaved.").run()
    [optimize] = [b for b in at.button if b.label == "Optimize Resume"]
    optimize.click().run()
    assert not at.exception
    assert box(at, "summary").value == "Backend engineer for high-traffic APIs."
    assert at.session_state["review_drafts"] == {} or "Unsaved." not in at.session_state["review_drafts"].values()


def test_nothing_changed_says_so(monkeypatch):
    monkeypatch.setattr("subprocess.run", fake_lualatex([]))
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["active_view"] = "Generator"
    at.session_state["resume_data"] = json.loads(json.dumps(PROFILE))
    at.session_state["optimized_resume_data"] = json.loads(json.dumps(PROFILE))
    at.run()
    assert not at.exception
    assert "nothing to review" in markdown_text(at)


# --- the preview when there is no generated PDF ---------------------------------

def test_preview_shows_the_optimized_version_not_the_profile(monkeypatch):
    """After e.g. a Draft Table edit clears the generated PDF, the preview
    falls back to a cached render of the optimized result - showing the
    Career Profile there made it look as if the rewrite had not happened."""
    rendered = []

    def capture(data, template_name, block_order):
        rendered.append(data.get("summary"))
        return b"%PDF-1.4 fake"

    monkeypatch.setattr("pdf_export.generate_preview_pdf_bytes", capture)
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["active_view"] = "Generator"
    at.session_state["resume_data"] = json.loads(json.dumps(PROFILE))
    at.session_state["optimized_resume_data"] = {**OPTIMIZED, "summary": "Unique optimized summary for fallback."}
    at.run()
    assert not at.exception
    assert rendered == ["Unique optimized summary for fallback."]


# --- collapsible sections ----------------------------------------------------------
# One expander per section (Summary, each job, each project, Skills, Cover
# letter), all closed to start with, so a long change list is a short list of
# headings. Each keeps its own open/closed state through edits and saves.

SECTION_PREFIXES = ("Summary", "Experience", "Projects", "Patents", "Skills", "Cover letter")


def sections(at):
    """Review section expanders, labels with the markdown escaping removed."""
    return [e for e in at.expander if e.label.replace("\\", "").startswith(SECTION_PREFIXES)]


def section_labels(at):
    return [e.label.replace("\\", "") for e in sections(at)]


def test_changes_are_grouped_into_sections_that_start_closed(monkeypatch):
    at = optimized_app(monkeypatch)
    assert section_labels(at) == [
        "Summary · 1 change",
        "Experience · Acme — Engineer · 1 change",
        "Projects · Old Game · 1 change",
    ]
    assert not any(e.proto.expanded for e in sections(at))
    # Closed sections still hold their edit boxes - nothing is lost by closing one.
    assert box(at, "summary").value == "Backend engineer for high-traffic APIs."


def test_expand_all_and_collapse_all(monkeypatch):
    at = optimized_app(monkeypatch)
    button(at, "review_expand_all").click().run()
    assert not at.exception
    assert all(e.proto.expanded for e in sections(at))
    button(at, "review_collapse_all").click().run()
    assert not any(e.proto.expanded for e in sections(at))


def test_a_section_with_unsaved_edits_says_so(monkeypatch):
    at = optimized_app(monkeypatch)
    box(at, "summary").input("My own summary.").run()
    assert section_labels(at)[0] == "Summary · 1 change · 1 unsaved"
    assert section_labels(at)[1] == "Experience · Acme — Engineer · 1 change"


def test_open_sections_stay_open_through_an_edit_and_a_save(monkeypatch):
    at = optimized_app(monkeypatch)
    button(at, "review_expand_all").click().run()
    box(at, "summary").input("My own summary.").run()
    assert all(e.proto.expanded for e in sections(at))
    button(at, "review_save").click().run()
    assert not at.exception
    assert all(e.proto.expanded for e in sections(at))


def test_closing_one_section_leaves_the_others_open(monkeypatch):
    """The saved open/closed state must follow the user's own toggles, not
    override them. AppTest cannot click an expander header, so the toggle is
    made the way the frontend reports it: through the expander's key."""
    import zlib
    at = optimized_app(monkeypatch)
    button(at, "review_expand_all").click().run()
    summary_key = f"review_section_{zlib.crc32('Summary'.encode('utf-8'))}_0"
    at.session_state[summary_key] = False
    at.run()
    assert [e.proto.expanded for e in sections(at)] == [False, True, True]
    box(at, "experience.0.details.0").input("Built REST APIs").run()
    assert [e.proto.expanded for e in sections(at)] == [False, True, True]
