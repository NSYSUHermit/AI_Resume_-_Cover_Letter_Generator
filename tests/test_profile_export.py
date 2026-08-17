"""Coverage for exporting a PDF straight from the Career Profile, with no
optimized result behind it.

Generate PDF used to be `disabled=optimized_resume_data is None`, so the only
way to get a PDF out of this app was to run (or paste) an AI rewrite first -
an API key and a JD to produce a document the profile JSON already fully
describes. The button now renders export_source_data(): the optimized result
when there is one, the profile itself otherwise.

lualatex is faked the same way tests/test_generator_preview.py does it, and
for the same reasons documented at length in that file's docstring: a
function defined inside app.py cannot be monkeypatched by dotted path under
AppTest (app.py re-executes as "__main__" on every run), while `subprocess`
is a real stdlib singleton that survives it. Every resume below gets a unique
heading.name so the process-wide @st.cache_data behind the base preview can
never serve another test's entry.
"""
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def run_app(**session_overrides):
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in session_overrides.items():
        at.session_state[key] = value
    at.run()
    return at


def fake_lualatex(calls):
    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(cmd, cwd=None, capture_output=None, text=None, **kwargs):
        calls.append(cmd)
        with open(os.path.join(cwd, cmd[-1].replace(".tex", ".pdf")), "wb") as f:
            f.write(b"%PDF-1.4 fake")
        return FakeCompletedProcess()

    return run


def profile(name, **overrides):
    data = {
        "heading": {"name": name, "email": "a@b.c", "phone": "", "website": "", "linkedin": ""},
        "summary": "Engineer.",
        "education": [],
        "experience": [{"company": "Acme", "role": "Engineer", "time_duration": "2020-2024",
                        "company_location": "", "details": [{"description": "Did things"}]}],
        "projects": [],
        "patents": [],
        "skills": {"set1": {"title": "Skills", "items": ["Python"]}},
        "cover_letter": "",
        "target_company": "",
        "target_role": "",
        "about me more": "",
    }
    data.update(overrides)
    return data


def generate_button(at):
    buttons = [b for b in at.button if b.label == "Generate PDF"]
    assert len(buttons) == 1, "Generate PDF button not found"
    return buttons[0]


# ---------------------------------------------------------------------------
# The button's enabled/disabled state
# ---------------------------------------------------------------------------

def test_generate_pdf_is_enabled_with_only_a_profile(monkeypatch):
    monkeypatch.setattr("subprocess.run", fake_lualatex([]))
    at = run_app(active_view="Generator", resume_data=profile("Enabled Probe"))
    assert not at.exception
    assert at.session_state["optimized_resume_data"] is None
    assert generate_button(at).disabled is False


def test_generate_pdf_is_disabled_with_an_empty_profile():
    at = run_app(active_view="Generator")
    assert not at.exception
    assert generate_button(at).disabled is True


def test_generate_pdf_stays_enabled_for_a_sparse_optimized_result(monkeypatch):
    """A manual-import result can be almost empty (only target_company is a
    real case - see tests/test_draft_table.py). resume_is_empty() would call
    that "empty"; the optimized path must not start refusing to export it."""
    monkeypatch.setattr("subprocess.run", fake_lualatex([]))
    at = run_app(
        active_view="Generator",
        resume_data=profile("Sparse Probe"),
        optimized_resume_data={"target_company": "Globex"},
    )
    assert not at.exception
    assert generate_button(at).disabled is False


# ---------------------------------------------------------------------------
# What it actually exports
# ---------------------------------------------------------------------------

def test_profile_export_produces_a_downloadable_resume(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", fake_lualatex(calls))
    at = run_app(active_view="Generator", resume_data=profile("Export Probe"))

    generate_button(at).click().run()

    assert not at.exception
    assert at.session_state["resume_preview_bytes"]
    # Named after the candidate, since a profile export has no target company.
    assert at.session_state["resume_dl_data"]["name"] == "Export_Probe_Resume.pdf"
    # No cover letter text in the profile -> no cover-letter PDF, not a crash.
    assert at.session_state["cl_dl_data"] is None


def test_profile_export_uses_target_fields_when_the_profile_has_them(monkeypatch):
    monkeypatch.setattr("subprocess.run", fake_lualatex([]))
    at = run_app(
        active_view="Generator",
        resume_data=profile("Target Probe", target_company="Globex", target_role="SWE"),
    )

    generate_button(at).click().run()

    assert not at.exception
    assert at.session_state["resume_dl_data"]["name"] == "Globex_SWE_Resume.pdf"


def test_profile_export_includes_the_cover_letter_when_the_profile_has_one(monkeypatch):
    monkeypatch.setattr("subprocess.run", fake_lualatex([]))
    at = run_app(
        active_view="Generator",
        resume_data=profile("Letter Probe", cover_letter="Dear hiring manager, ..."),
    )

    generate_button(at).click().run()

    assert not at.exception
    assert at.session_state["cl_dl_data"]["name"] == "Letter_Probe_CL.pdf"


def test_optimized_result_still_wins_over_the_profile(monkeypatch):
    """export_source_data()'s precedence: with both present, the optimized
    result is what gets rendered - the profile fallback must not regress the
    normal flow."""
    monkeypatch.setattr("subprocess.run", fake_lualatex([]))
    at = run_app(
        active_view="Generator",
        resume_data=profile("Precedence Probe"),
        optimized_resume_data={
            "target_company": "Globex", "target_role": "SWE",
            "heading": {"name": "Precedence Probe"}, "skills": {},
        },
    )

    generate_button(at).click().run()

    assert not at.exception
    assert at.session_state["resume_dl_data"]["name"] == "Globex_SWE_Resume.pdf"


# ---------------------------------------------------------------------------
# Tracker interaction
# ---------------------------------------------------------------------------

def test_profile_export_is_not_recorded_in_the_tracker(monkeypatch):
    """sync_application_to_tracker() reads optimized_resume_data.get(...) on
    every line; a profile-only export has no optimized result, so recording
    it would both crash and put a blank row in the tracker. The download
    button must still work - just without a tracker write."""
    monkeypatch.setattr("subprocess.run", fake_lualatex([]))
    at = run_app(
        active_view="Generator",
        logged_in=True,
        user_email="probe@example.com",
        resume_data=profile("Tracker Probe"),
    )
    generate_button(at).click().run()
    assert not at.exception

    downloads = [d for d in at.get("download_button")]
    assert len(downloads) == 1
    downloads[0].click().run()

    assert not at.exception
    assert at.session_state["tracked_application_id"] is None
    captions = [c.value for c in at.caption]
    assert any("not recorded in the tracker" in c for c in captions)
