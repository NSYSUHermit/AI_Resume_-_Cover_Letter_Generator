import streamlit as st
import jinja2
from datetime import datetime
import subprocess
import os
import json
import tempfile
import shutil
import base64
import html
import streamlit.components.v1 as components
from firebase_dashboard import init_firebase, authenticate_user, register_user, render_dashboard, save_application, render_interview_progress, save_user_profile, load_user_profile, fetch_applications
from ui_feedback import run_ai_call
from theme import TOKENS, FONT_STACK, css_root_block
import ai
import workspace

st.set_page_config(page_title="AI Resume", page_icon="AI", layout="wide")

def get_db():
    return init_firebase()

# ---------------------------------------------------------
# 初始化 Session State
# ---------------------------------------------------------
def default_resume_data():
    """A blank profile.

    The app used to open with a fake "John Doe" resume, and every new user had
    to work out that the data on screen was not theirs before they could start.
    """
    return {
        "heading": { "name": "", "email": "", "phone": "", "website": "", "linkedin": "" },
        "cover_letter": "", "target_company": "", "target_role": "", "about me more": "", "summary": "", "education": [], "experience": [], "projects": [], "patents": [], "skills": { "set1": { "title": "Skills", "items": [] } }
    }

def resume_is_empty(data):
    data = data or {}
    if any((data.get("heading") or {}).get(field) for field in ("name", "email", "phone")):
        return False
    if data.get("summary"):
        return False
    return not any(data.get(section) for section in ("education", "experience", "projects", "patents"))

if "resume_data" not in st.session_state:
    st.session_state.resume_data = default_resume_data()

if "optimized_resume_data" not in st.session_state: st.session_state.optimized_resume_data = None
if "base_editor_key" not in st.session_state: st.session_state.base_editor_key = 0
if "opt_editor_key" not in st.session_state: st.session_state.opt_editor_key = 0
if "ats_metrics" not in st.session_state: st.session_state.ats_metrics = None
if "changelog" not in st.session_state: st.session_state.changelog = ""
if "custom_prompt" not in st.session_state:
    st.session_state.custom_prompt = """You are an elite Career Strategist and ATS Architect. Overhaul the resume and cover letter based on the JD:
1. **Resume (STAR Method)**: Rewrite every experience bullet point using the STAR method (Situation, Task, Action, Result). Keep them concise (1-2 lines) but highly impactful. Surface any metric the original bullet already contains; if it has none, write the strongest accurate version and leave the number out.
2. **Aggressive Action Verbs**: Use high-ownership verbs like 'Spearheaded', 'Engineered', 'Orchestrated', 'Pioneered'.
3. **ATS Semantic Mapping**: Naturally emphasise the JD's vocabulary where the resume already provides evidence for it. Do not claim a tool or skill the resume never mentions.
4. **Cover Letter**: Generate a compelling 3-paragraph letter.
   - Para 1: Strong hook and immediate value proposition.
   - Para 2: Concrete evidence of 2-3 skills matching the JD's 'Required' section.
   - Para 3: Passion for the company's mission and a clear call to action.
5. **Formatting**: Return ONLY valid JSON. Do NOT use markdown like '**' inside the strings."""
if "api_key" not in st.session_state: st.session_state.api_key = ""
# Durable copy of the JD. Streamlit drops widget keys on any rerun where the
# widget is not rendered, so keeping the JD only in the text area's own key lost
# it the moment the user switched workspace.
if "jd_text" not in st.session_state: st.session_state.jd_text = ""
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_email" not in st.session_state: st.session_state.user_email = ""
if "resume_preview_bytes" not in st.session_state: st.session_state.resume_preview_bytes = None
if "cover_letter_preview_bytes" not in st.session_state: st.session_state.cover_letter_preview_bytes = None
if "resume_dl_data" not in st.session_state: st.session_state.resume_dl_data = None
if "cl_dl_data" not in st.session_state: st.session_state.cl_dl_data = None
if "ats_analysis" not in st.session_state: st.session_state.ats_analysis = None
if "optimized_source_snapshot" not in st.session_state: st.session_state.optimized_source_snapshot = None
# Requirements the rewrite refused to claim because the resume had no evidence.
if "suggested_metrics" not in st.session_state: st.session_state.suggested_metrics = []
if "jd_screening" not in st.session_state: st.session_state.jd_screening = None
if "last_synced_snapshot" not in st.session_state: st.session_state.last_synced_snapshot = None
if "last_synced_at" not in st.session_state: st.session_state.last_synced_at = None
# 一次 optimize 就是一份投遞。save_application 不去重，靠這個值擋住重複寫入。
if "tracked_application_id" not in st.session_state: st.session_state.tracked_application_id = None
# Plain state, not a widget key: the sidebar nav is built from buttons, so
# nothing owns this value except us.
if "sidebar_collapsed" not in st.session_state: st.session_state.sidebar_collapsed = False
if "active_view" not in st.session_state:
    st.session_state.active_view = workspace.initial_view(
        resume_is_empty(st.session_state.resume_data)
    )

def set_result_banner(title, details=None, actions=None):
    """Record what an AI run produced, so it can be shown after the rerun.

    The status panel is destroyed by the rerun that follows a successful call,
    which left a four-second toast as the only confirmation of a thirty-second
    operation. This survives until the next run or an explicit dismiss.
    """
    st.session_state.result_banner = {
        "title": title,
        "details": [d for d in (details or []) if d],
        "actions": actions or [],
    }

def render_result_banner():
    banner = st.session_state.get("result_banner")
    if not banner:
        return
    with st.container(border=True, key="result_banner"):
        text_col, close_col = st.columns([20, 1])
        with text_col:
            st.markdown(f"**{banner['title']}**")
            if banner["details"]:
                st.caption("  ·  ".join(banner["details"]))
        with close_col:
            if st.button("✕", key="dismiss_result_banner", help="Dismiss"):
                del st.session_state.result_banner
                st.rerun()
        if banner["actions"]:
            action_cols = st.columns(len(banner["actions"]) + 2)
            for col, (action_label, target_view) in zip(action_cols, banner["actions"]):
                with col:
                    if st.button(action_label, key=f"banner_to_{target_view}", use_container_width=True):
                        st.session_state.active_view = target_view
                        del st.session_state.result_banner
                        st.rerun()

def clear_pdf_outputs():
    st.session_state.resume_preview_bytes = None
    st.session_state.cover_letter_preview_bytes = None
    st.session_state.resume_dl_data = None
    st.session_state.cl_dl_data = None

def clear_generated_outputs():
    st.session_state.optimized_resume_data = None
    st.session_state.ats_metrics = None
    st.session_state.ats_analysis = None
    st.session_state.changelog = ""
    st.session_state.suggested_metrics = []
    st.session_state.jd_screening = None
    st.session_state.optimized_source_snapshot = None
    st.session_state.result_banner = None
    clear_pdf_outputs()
    st.session_state.tracked_application_id = None

def start_new_application():
    """Reset everything that belongs to one job application.

    Cleared: the JD, the optimized result, ATS, the PDFs, and
    tracked_application_id - so the next download opens a fresh tracker row
    instead of being suppressed by the dedupe guard.

    Kept: the Career Profile itself, the saved Custom Strategy, the login, the
    API key. Those are settings, not per-application state.

    The base_editor_key bump is load-bearing, not cosmetic. The JD mirrors from
    a widget keyed jd_input_{base_editor_key} into st.session_state.jd_text;
    clearing only jd_text leaves the old widget holding the previous text, and
    it writes it straight back on the next rerun. A new key forces a fresh
    widget that initialises from the cleared value. (Custom Strategy rides the
    same key but re-initialises from custom_prompt, so it survives - which is
    what we want.)
    """
    clear_generated_outputs()
    st.session_state.jd_text = ""
    st.session_state.base_editor_key += 1


def clear_pdf_outputs_and_tracking():
    """clear_pdf_outputs() plus resetting the tracker dedupe flag.

    For the manual-import paths that replace optimized_resume_data wholesale
    (Manual Result Import, Manual Data Import, Advanced Optimized JSON
    Import): they cannot call clear_generated_outputs() because that would
    also wipe the ats_analysis/changelog/etc they are about to set from the
    freshly imported JSON. But tracked_application_id still has to reset —
    otherwise it survives from whatever application was recorded before the
    import, and should_record_application() silently blocks the write for
    the new (possibly different) result. edit_opt_dialog()'s "Save Changes"
    handler deliberately does NOT call this: editing fields of the current
    result is the same application, not a new one, and writing a second row
    there is exactly what the guard exists to prevent.
    """
    clear_pdf_outputs()
    st.session_state.tracked_application_id = None

def resume_snapshot(data):
    return json.dumps(data or {}, ensure_ascii=False, sort_keys=True)

def optimized_result_is_stale():
    snapshot = st.session_state.get("optimized_source_snapshot")
    return snapshot is not None and resume_snapshot(st.session_state.resume_data) != snapshot

def profile_snapshot():
    return json.dumps(
        {"resume": st.session_state.resume_data, "prompt": st.session_state.custom_prompt},
        ensure_ascii=False,
        sort_keys=True,
    )

def mark_profile_synced():
    st.session_state.last_synced_snapshot = profile_snapshot()
    st.session_state.last_synced_at = datetime.now().strftime("%H:%M")

def autosave_profile():
    """Write the profile back to Firestore whenever it actually changed.

    This replaces the old Push/Pull buttons. New users never worked out that
    they had to press Push, so a browser refresh silently discarded everything
    they had typed. Comparing snapshots keeps writes down to real edits.
    """
    if not st.session_state.logged_in or not st.session_state.user_email:
        return
    snapshot = profile_snapshot()
    if snapshot == st.session_state.get("last_synced_snapshot"):
        return
    cloud_db = get_db()
    if cloud_db is None:
        return
    ok, msg = save_user_profile(
        cloud_db,
        st.session_state.user_email,
        st.session_state.resume_data,
        st.session_state.custom_prompt,
        st.session_state.get("api_key", ""),
    )
    if ok:
        mark_profile_synced()
        st.session_state.sync_error = None
    else:
        st.session_state.sync_error = msg

def clear_user_session():
    """Drop everything tied to the signed-in account.

    Logging out previously left `user_email`, `app_records`, `resume_data` and
    `api_key` in place, so the next account to sign in from the same browser
    session inherited the previous user's data.
    """
    st.session_state.logged_in = False
    st.session_state.user_email = ""
    st.session_state.api_key = ""
    st.session_state.resume_data = default_resume_data()
    # Recompute now that resume_data is empty again — otherwise a logout (or
    # a Reset All Data, which also routes through this function via the
    # pending_reset flag below) from Generator left active_view on Generator,
    # showing "Your Career Profile is empty" instead of landing back on
    # Profile. Same call as session init (near the top of this file) and
    # post-login, just recomputed for the opposite direction.
    st.session_state.active_view = workspace.initial_view(
        resume_is_empty(st.session_state.resume_data)
    )
    st.session_state.base_editor_key += 1
    st.session_state.jd_text = ""
    st.session_state.app_records = []
    st.session_state.force_refresh_apps = True
    st.session_state.last_synced_snapshot = None
    st.session_state.last_synced_at = None
    clear_generated_outputs()

def safe_filename_part(value, fallback):
    text = str(value or fallback).strip().replace(" ", "_")
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)
    return cleaned.strip("_") or fallback

def render_json_editor(value, key, height=500):
    return st.text_area(
        "JSON Editor",
        value=value,
        key=key,
        height=height,
        label_visibility="collapsed",
    )

def editor_rows(value):
    if hasattr(value, "to_dict"):
        return value.to_dict("records")
    if isinstance(value, list):
        return value
    return []

def compact_rows(rows, fields):
    cleaned = []
    for row in editor_rows(rows):
        # A row is not always a dict: editable_seed()/editor_rows() pass a
        # list straight through unchanged (unlike experience_seed_rows(),
        # which already filters to dicts), so a malformed optimized_resume_data
        # - e.g. {"education": ["MIT BS"]} instead of a list of {"school":
        # ...} dicts, reachable via Manual Data Import's free-form JSON paste,
        # or ai.rewrite_resume(), which does not validate element shapes -
        # seeds this with bare strings. row.get(...) below would crash the
        # whole draft table (and everything the Generator view renders after
        # it) over one bad row; skip what cannot be read as a row instead and
        # let the table degrade to showing what it can.
        if not isinstance(row, dict):
            continue
        item = {field: str(row.get(field, "") or "").strip() for field in fields}
        if any(item.values()):
            cleaned.append(item)
    return cleaned

def editable_seed(rows, fields):
    rows = editor_rows(rows)
    if rows:
        return rows
    return [{field: "" for field in fields}]

def details_to_text(details):
    if isinstance(details, str):
        # A malformed optimized_resume_data can carry "details" as an
        # already-joined string instead of a list of {"description": ...}
        # dicts (ai.rewrite_resume() does not validate element shapes, and
        # Manual Data Import accepts arbitrary pasted JSON). Falling through
        # to the loop below would iterate the string CHARACTER BY CHARACTER
        # ("details or []" is truthy for any non-empty string, so the for
        # loop walks it directly) - silently exploding one bullet into one
        # row per letter the next time anything round-trips through
        # text_to_details(), its inverse. Treat a string as already the text
        # this function exists to produce instead.
        return "\n".join(line.strip() for line in details.splitlines() if line.strip())
    lines = []
    for detail in details or []:
        if isinstance(detail, dict):
            text = detail.get("description", "")
        else:
            text = str(detail)
        if str(text).strip():
            lines.append(str(text).strip())
    return "\n".join(lines)

def text_to_details(text):
    return [{"description": line.strip()} for line in str(text or "").splitlines() if line.strip()]

def skills_to_rows(skills):
    rows = []
    if isinstance(skills, dict):
        for key, value in skills.items():
            if isinstance(value, dict):
                items = value.get("items", [])
                if isinstance(items, str):
                    items_text = items
                else:
                    items_text = ", ".join(str(item) for item in items)
                rows.append({
                    "key": key,
                    "title": value.get("title", ""),
                    "items": items_text,
                })
    return rows or [{"key": "set1", "title": "Skills", "items": ""}]

def rows_to_skills(rows):
    skills = {}
    for index, row in enumerate(editor_rows(rows), start=1):
        key = str(row.get("key", "") or f"set{index}").strip() or f"set{index}"
        title = str(row.get("title", "") or "").strip()
        items_text = str(row.get("items", "") or "")
        items = [item.strip() for item in items_text.split(",") if item.strip()]
        if title or items:
            skills[key] = {"title": title or "Skills", "items": items}
    return skills or {"set1": {"title": "Skills", "items": []}}

# Shared field lists for the two grids ("experience" needs its own seed/rows
# helpers below because "details" round-trips through a joined-text column;
# education and projects are plain enough that editable_seed()/compact_rows()
# need only the field list). Shared between render_resume_form_editor() (Profile
# view and edit_opt_dialog()) and render_optimized_draft_table() (the draft
# table) so the two editable-grid surfaces cannot silently drift on field names.
EXPERIENCE_ROW_FIELDS = ["company", "role", "time_duration", "company_location", "details"]
EDUCATION_ROW_FIELDS = ["school", "time_period", "degree", "school_location"]
PROJECT_ROW_FIELDS = ["name", "time", "description"]

def experience_seed_rows(experience_list):
    """experience list (schema shape) -> st.data_editor row dicts."""
    rows = []
    for exp in experience_list or []:
        if isinstance(exp, dict):
            rows.append({
                "company": exp.get("company", ""),
                "role": exp.get("role", ""),
                "time_duration": exp.get("time_duration", ""),
                "company_location": exp.get("company_location", ""),
                "details": details_to_text(exp.get("details", [])),
            })
    return editable_seed(rows, EXPERIENCE_ROW_FIELDS)

def rows_to_experience(rows):
    """Inverse of experience_seed_rows(): st.data_editor rows -> experience list."""
    experience = []
    for row in compact_rows(rows, EXPERIENCE_ROW_FIELDS):
        experience.append({
            "company": row["company"],
            "role": row["role"],
            "time_duration": row["time_duration"],
            "company_location": row["company_location"],
            "details": text_to_details(row["details"]),
        })
    return experience

def render_resume_form_editor(data, key_prefix):
    data = json.loads(json.dumps(data or {}, ensure_ascii=False))
    heading = data.get("heading") if isinstance(data.get("heading"), dict) else {}

    st.markdown("#### Profile Fields")
    with st.container(border=True):
        st.subheader("Basic Info")
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Name", value=heading.get("name", ""), key=f"{key_prefix}_name")
            email = st.text_input("Email", value=heading.get("email", ""), key=f"{key_prefix}_email")
            phone = st.text_input("Phone", value=heading.get("phone", ""), key=f"{key_prefix}_phone")
        with c2:
            website = st.text_input("Website", value=heading.get("website", ""), key=f"{key_prefix}_website")
            linkedin = st.text_input("LinkedIn", value=heading.get("linkedin", ""), key=f"{key_prefix}_linkedin")
            target_role = st.text_input("Target Role", value=data.get("target_role", ""), key=f"{key_prefix}_target_role")
        target_company = st.text_input("Target Company", value=data.get("target_company", ""), key=f"{key_prefix}_target_company")
        summary = st.text_area("Summary", value=data.get("summary", ""), height=130, key=f"{key_prefix}_summary")
        about_more = st.text_area("About Me / Notes", value=data.get("about me more", ""), height=90, key=f"{key_prefix}_about")
        cover_letter = st.text_area("Cover Letter", value=data.get("cover_letter", ""), height=180, key=f"{key_prefix}_cover_letter")

    with st.container(border=True):
        st.subheader("Education")
        education_rows = st.data_editor(
            editable_seed(data.get("education", []), EDUCATION_ROW_FIELDS),
            key=f"{key_prefix}_education",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "school": st.column_config.TextColumn("School"),
                "time_period": st.column_config.TextColumn("Time Period"),
                "degree": st.column_config.TextColumn("Degree"),
                "school_location": st.column_config.TextColumn("Location"),
            },
        )

    exp_seed = experience_seed_rows(data.get("experience", []))
    with st.container(border=True):
        st.subheader("Experience")
        experience_rows = st.data_editor(
            exp_seed,
            key=f"{key_prefix}_experience",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "company": st.column_config.TextColumn("Company"),
                "role": st.column_config.TextColumn("Role"),
                "time_duration": st.column_config.TextColumn("Time Duration"),
                "company_location": st.column_config.TextColumn("Location"),
                "details": st.column_config.TextColumn("Bullet Points (one per line)", width="large"),
            },
        )

    with st.container(border=True):
        st.subheader("Projects")
        project_rows = st.data_editor(
            editable_seed(data.get("projects", []), PROJECT_ROW_FIELDS),
            key=f"{key_prefix}_projects",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "name": st.column_config.TextColumn("Name"),
                "time": st.column_config.TextColumn("Time"),
                "description": st.column_config.TextColumn("Description", width="large"),
            },
        )

    with st.container(border=True):
        st.subheader("Patents")
        patent_rows = st.data_editor(
            editable_seed(data.get("patents", []), ["name", "time", "description"]),
            key=f"{key_prefix}_patents",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "name": st.column_config.TextColumn("Name"),
                "time": st.column_config.TextColumn("Time"),
                "description": st.column_config.TextColumn("Description", width="large"),
            },
        )

    with st.container(border=True):
        st.subheader("Skills")
        skill_rows = st.data_editor(
            skills_to_rows(data.get("skills", {})),
            key=f"{key_prefix}_skills",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "key": st.column_config.TextColumn("Set Key"),
                "title": st.column_config.TextColumn("Category"),
                "items": st.column_config.TextColumn("Items (comma separated)", width="large"),
            },
        )

    experience = rows_to_experience(experience_rows)

    return {
        **data,
        "heading": {
            "name": name,
            "email": email,
            "phone": phone,
            "website": website,
            "linkedin": linkedin,
        },
        "target_company": target_company,
        "target_role": target_role,
        "cover_letter": cover_letter,
        "about me more": about_more,
        "summary": summary,
        "education": compact_rows(education_rows, EDUCATION_ROW_FIELDS),
        "experience": experience,
        "projects": compact_rows(project_rows, PROJECT_ROW_FIELDS),
        "patents": compact_rows(patent_rows, ["name", "time", "description"]),
        "skills": rows_to_skills(skill_rows),
    }

def sync_application_to_tracker():
    if not workspace.should_record_application(
        is_tracked=st.session_state.tracked_application_id is not None,
        logged_in=st.session_state.logged_in,
    ):
        return
    tracker_db = get_db()
    if tracker_db is None:
        st.error("Tracker is unavailable until Firebase secrets are configured.")
        return
    ok = save_application(
        tracker_db,
        st.session_state.user_email,
        st.session_state.optimized_resume_data.get('target_company'),
        st.session_state.optimized_resume_data,
        st.session_state.get('jd_text', ""),
    )
    if not ok:
        # save_application 內部吞掉例外只回傳 False，不檢查回傳值就會把失敗的寫入也標成已記錄。
        return
    # 記下來就好，值本身只是「已記錄」的旗標。
    st.session_state.tracked_application_id = st.session_state.optimized_resume_data.get('target_company') or "recorded"
    st.session_state.pending_toast = "Recorded to tracker."
    # render_preview 是 @st.fragment。"Saved to tracker" 那格進度在
    # render_progress_strip()，在 fragment 之外，不會跟著 fragment-scoped
    # rerun 更新——使用者得再點別的東西才看得到。跟 render_export_settings
    # 同樣的作法：app-scope st.rerun()（預設值 scope="app"）逼出全頁重繪。
    st.rerun()

# ---------------------------------------------------------
# AI 核心邏輯 (prompts and scoring live in ai.py)
# ---------------------------------------------------------
def check_api_key(api_key, report=lambda m: None):
    report("Sending a test request to Gemini...")
    return ai.test_api_key(api_key)

def parse_pdf_resume_to_json(pdf_bytes, api_key, report=lambda m: None):
    if not api_key: return False, "Missing API Key.", None
    try:
        report(f"Uploading {len(pdf_bytes) // 1024} KB to Gemini...")
        data = ai.parse_resume_pdf(pdf_bytes, api_key)
        roles = len(data.get("experience") or [])
        schools = len(data.get("education") or [])
        skills = sum(len((s or {}).get("items") or []) for s in (data.get("skills") or {}).values())
        report(f"Read {roles} roles, {schools} schools, {skills} skills")
        return True, "Done", data
    except Exception as e:
        return False, str(e), None

def ai_optimize_and_update(jd_text, custom_prompt, report=lambda m: None):
    """Screen the JD, then rewrite against it, then score the result locally.

    Splitting what used to be a single call means the rewrite prompt has one
    job, a malformed response costs half as much work, the keyword list is
    produced before the rewrite exists rather than by the model marking itself,
    and each stage has something true to report while the user waits.
    """
    api_key = st.session_state.get("api_key")
    if not api_key: return False, "Missing API Key."

    report("Reading the job description...")
    try:
        screening = ai.screen_job_description(jd_text, api_key)
    except Exception as e:
        return False, f"Job description screening failed: {e}"

    st.session_state.jd_screening = screening
    company = screening.get("target_company") or ""
    role = screening.get("target_role") or ""
    keywords = screening.get("keywords", [])
    target = " · ".join(p for p in (company, role) if p) or "this role"
    report(f"Target: {target} — {len(keywords)} requirements extracted")

    if screening.get("visa_blocked"):
        reason = screening.get("reason") or "This posting rules out visa sponsorship."
        return False, f"Visa check stopped this run: {reason}"

    report("Rewriting your resume against those requirements...")
    try:
        rewrite = ai.rewrite_resume(jd_text, st.session_state.resume_data, custom_prompt, api_key)
    except Exception as e:
        return False, f"Resume rewrite failed: {e}"

    optimized = rewrite.get("optimized_resume") or {}
    if not optimized:
        return False, "The rewrite returned no resume."

    # The screening call already read these off the JD; prefer them so the
    # filename and the tracker entry do not depend on the rewrite call.
    if not optimized.get("target_company"):
        optimized["target_company"] = company
    if not optimized.get("target_role"):
        optimized["target_role"] = role

    suggested = rewrite.get("suggested_metrics", []) or []
    report("Scoring keyword coverage...")
    metrics = ai.keyword_report(keywords, st.session_state.resume_data, optimized)
    report(f"Coverage {metrics['original_pct']}% → {metrics['optimized_pct']}%")

    st.session_state.optimized_resume_data = optimized
    st.session_state.changelog = rewrite.get("changelog", "")
    st.session_state.suggested_metrics = suggested
    st.session_state.optimized_source_snapshot = resume_snapshot(st.session_state.resume_data)
    st.session_state.opt_editor_key += 1
    st.session_state.ats_metrics = metrics
    st.session_state.ats_analysis = {"screening": screening, "rewrite": rewrite}

    set_result_banner(
        title=f"Resume optimised for {target}",
        details=[
            f"Keyword coverage {metrics['original_pct']}% → {metrics['optimized_pct']}%",
            f"{len(metrics['newly_added'])} newly covered" if metrics["newly_added"] else None,
            f"{len(suggested)} facts to add yourself" if suggested else None,
        ],
        # "ATS" and "Review" are no longer separate destinations to jump to —
        # both are already part of the Generator view the user is looking at.
        actions=[],
    )
    return True, "Done"

# ---------------------------------------------------------
# PDF 渲染
# ---------------------------------------------------------
def render_pdf_js(pdf_bytes, height=800):
    """Render every page of a PDF inline with pdf.js.

    This used to take a `max_pages` cap, defaulting to one page behind a
    "Render all pages" checkbox, on the stated grounds that re-embedding the
    document as base64 is the most expensive thing this app does on a rerun.
    That reasoning was wrong: `base64.b64encode` below runs over the whole
    document regardless of the cap, which only ever limited how many canvases
    pdf.js painted client-side. The expensive half was paid either way, so the
    cap bought nothing and cost the user a click plus the hidden pages.

    If the base64 re-embed ever needs fixing for real, cache it on a hash of
    `pdf_bytes` — that is the part that is actually expensive.

    Canvases are appended synchronously in page order; an earlier version
    appended them from the getPage callback, so pages could land out of order
    whenever one resolved before an earlier one.
    """
    if not pdf_bytes: return
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_js_html = f"""<!DOCTYPE html><html><head>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<style>
body{{margin:0;background:#0f172a;display:flex;flex-direction:column;align-items:center;padding:10px;}}
canvas{{margin-bottom:10px;border:1px solid #334155;max-width:98%;}}
#note{{color:#94a3b8;font:13px {FONT_STACK};padding:6px 10px;text-align:center;}}
</style></head><body><div id="p"></div><div id="note"></div><script>
pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
var b=window.atob('{base64_pdf}');
var bytes=new Uint8Array(b.length);
for(var i=0;i<b.length;i++)bytes[i]=b.charCodeAt(i);
pdfjsLib.getDocument({{data:bytes}}).promise.then(function(pdf){{
  var last=pdf.numPages;
  for(var i=1;i<=last;i++){{
    (function(n){{
      var c=document.createElement('canvas');
      document.getElementById('p').appendChild(c);
      pdf.getPage(n).then(function(page){{
        var v=page.getViewport({{scale:1.3}});
        c.height=v.height;c.width=v.width;
        page.render({{canvasContext:c.getContext('2d'),viewport:v}});
      }});
    }})(i);
  }}
  document.getElementById('note').textContent=pdf.numPages+(pdf.numPages===1?' page':' pages');
}});</script></body></html>"""
    components.html(pdf_js_html, height=height, scrolling=True)

def escape_latex_chars(obj):
    """Recursively escape LaTeX special characters to prevent compilation errors."""
    if isinstance(obj, str):
        latex_escape_map = {
            '\\': r'\textbackslash{}',
            '$': r'\$',
            '%': r'\%',
            '&': r'\&',
            '＆': r'\&',
            '_': r'\_',
            '#': r'\#',
            '{': r'\{',
            '}': r'\}',
            '~': r'\textasciitilde{}',
            '^': r'\textasciicircum{}',
        }
        return "".join(latex_escape_map.get(ch, ch) for ch in obj)
    elif isinstance(obj, list):
        return [escape_latex_chars(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: escape_latex_chars(v) for k, v in obj.items()}
    return obj

def template_file_for(template_label):
    """Map the Template selectbox's label to its .tex file.

    Shared by render_export_settings() (the real export, left column) and
    render_preview()'s cached base-resume preview (right column) so the two
    can never silently drift apart on what "Tech" / "Business" resolve to.
    """
    return "main.tex" if "Tech" in template_label else "elsa_main.tex"

def generate_preview_pdf_bytes(data, template_name, block_order):
    try:
        escaped_data = escape_latex_chars(data)
        with tempfile.TemporaryDirectory() as td:
            shutil.copy(template_name, td)
            tp = os.path.join(td, template_name)
            with open(tp, "r", encoding="utf-8") as f: c = f.read()
            if block_order and "BLOCKS_PLACEHOLDER" in c:
                bs = ""
                for b in block_order:
                    if b == "Summary": bs += "\\directlua{printSummary()}\n"
                    elif b == "Experience": bs += "\\section{WORK EXPERIENCE}\n\\directlua{printExperience()}\n"
                    elif b == "Education": bs += "\\section{EDUCATION}\n\\directlua{printEducation()}\n"
                    elif b == "Projects & Patents": bs += "\\directlua{printProjectsAndPatents()}\n"
                    elif b == "Skills": bs += "\\section{SKILLS}\n\\directlua{printSkills()}\n"
                c = c.replace("BLOCKS_PLACEHOLDER", bs)
                with open(tp, "w", encoding="utf-8") as f: f.write(c)
            with open(os.path.join(td, "ml_resume.json"), "w", encoding="utf-8") as f: json.dump(escaped_data, f, ensure_ascii=False)
            result = subprocess.run(['lualatex', '-interaction=nonstopmode', template_name], cwd=td, capture_output=True, text=True)
            if result.returncode != 0:
                st.error("Resume PDF generation failed. Check the LaTeX log below.")
                st.code((result.stdout or result.stderr or "")[-4000:], language="text")
                return None
            op = tp.replace(".tex", ".pdf")
            if os.path.exists(op): return open(op, "rb").read()
            st.error("Resume PDF generation finished without producing a PDF.")
    except Exception as e:
        st.error(f"Resume PDF generation error: {e}")
    return None

class PreviewCompileFailed(Exception):
    """Raised by base_preview_pdf() on a failed compile - see its docstring.

    Never meant to reach a user; render_preview() catches it right where it
    calls base_preview_pdf() and shows the same "Preview unavailable" message
    a returned None used to produce.
    """

@st.cache_data(show_spinner="Compiling your resume preview...", max_entries=8)
def base_preview_pdf(snapshot, template_name, block_order):
    """Base 履歷的預覽。

    以 snapshot 字串當 key，履歷沒變就不會重新編譯。lualatex 要跑好幾秒，
    每次 rerun 都編譯一次會讓整個 app 失去反應。

    show_spinner carries a real message, not False: a genuine first-time
    compile (a cache miss) used to run for several seconds with no visible
    indication at all - a gap Task 2 flagged rather than caused (the design
    doc's own spec asked for show_spinner=False; closing the gap it left is
    this task's job). st.cache_data's own show_spinner mechanism is
    hit/miss-aware at the framework level, confirmed by reading
    streamlit/runtime/caching/cache_utils.py's
    CachedFunc._get_or_create_cached_value(): a cache hit returns via
    _handle_cache_hit() and never even constructs the spinner context
    manager, which only wraps the miss path's _handle_cache_miss() call.
    st.spinner() itself additionally debounces via a 0.5s timer
    (elements/spinner.py's DELAY_SECS) that gets cancelled before enqueueing
    anything if the wrapped call finishes first. Both together mean a cache
    hit stays completely silent and instant with zero custom bookkeeping
    here, and only a genuine multi-second compile ever shows anything -
    exactly the contract this task asks for, without reimplementing that
    hit/miss + debounce logic by hand. Styled via the .stCacheSpinner hook in
    the stylesheet to carry the app's brand colour instead of Streamlit's
    default, so it reads as part of the same visual language as the rest of
    this redesign rather than a generic system spinner.

    `block_order` must be a tuple, not a list, from the caller: lists are not
    hashable, and st.cache_data hashes every argument to build the cache key.
    generate_preview_pdf_bytes only ever iterates/truth-tests it, so a tuple
    works there unchanged, but it's converted back to a list anyway to keep
    that function's contract (a list) exactly as it was before this wrapper
    existed.

    Raises PreviewCompileFailed instead of returning None on a failed
    compile (UI final-review fix wave, Minor 9): generate_preview_pdf_bytes()
    returns None on a LaTeX failure, and a plain `return None` here would
    cache that None under this call's (snapshot, template_name, block_order)
    key exactly like any other result, so a transient lualatex failure would
    stick until one of those three changed. st.cache_data only writes a
    result to the cache after this function returns (confirmed by reading
    streamlit==1.61.1's own runtime/caching/cache_utils.py -
    CachedFunc._handle_cache_miss() calls cache.write_result() only after
    self._info.func(...) returns, with nothing catching an exception raised
    from that call in between - and empirically: a cache_data-wrapped
    function made to raise on every call was confirmed to re-run on every
    call, not just the first), so raising instead of returning means a later
    call with the very same arguments retries the compile instead of
    replaying the old failure. The error itself was already shown via
    st.error/st.code inside generate_preview_pdf_bytes() above; this only
    keeps that failure from being remembered.
    """
    pdf_bytes = generate_preview_pdf_bytes(json.loads(snapshot), template_name, list(block_order))
    if pdf_bytes is None:
        raise PreviewCompileFailed()
    return pdf_bytes

def generate_cover_letter_pdf_bytes(data):
    try:
        # 獲取內容與標頭資訊 (由使用者要求恢復專業版面)
        txt = data.get('cover_letter') or data.get('coverLetter') or data.get('Cover Letter', '')
        if not txt: return None
        
        escaped_data = escape_latex_chars(data)
        escaped_txt = escape_latex_chars(txt)
        
        heading = escaped_data.get('heading', {})
        name = heading.get('name', 'Your Name')
        email = heading.get('email', '')
        phone = heading.get('phone', '')
        linkedin = heading.get('linkedin', '')
        website = heading.get('website', '')

        # 使用自定義 Jinja2 環境，避免與 LaTeX 的 {} 衝突 (由使用者回報錯誤修復)
        latex_jinja_env = jinja2.Environment(
            block_start_string='<%-',
            block_end_string='%>',
            variable_start_string='<<',
            variable_end_string='>>',
            comment_start_string='<#',
            comment_end_string='#>',
            line_statement_prefix='%%',
            line_comment_prefix='%#',
            trim_blocks=True,
            autoescape=False,
            loader=jinja2.FileSystemLoader(os.path.abspath('.'))
        )
        template = latex_jinja_env.get_template('cover_letter.tex')
        
        # 準備資料
        template_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "linkedin": linkedin,
            "website": website,
            "body": escaped_txt.replace("\n", "\n\n").replace('**', '')
        }
        
        rendered_tex = template.render(template_data)

        with tempfile.TemporaryDirectory() as td:
            tex_path = os.path.join(td, "c.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(rendered_tex)
            
            result = subprocess.run(['lualatex', '-interaction=nonstopmode', 'c.tex'], cwd=td, capture_output=True, text=True)
            if result.returncode != 0:
                st.error("Cover Letter PDF generation failed. Check the LaTeX log below.")
                st.code((result.stdout or result.stderr or "")[-4000:], language="text")
                return None
            pdf_path = os.path.join(td, "c.pdf")
            if os.path.exists(pdf_path):
                return open(pdf_path, "rb").read()
    except Exception as e:
        st.error(f"Cover Letter generation error: {e}")
        return None

# 🔔 處理 Rerun 後的延遲動作 (必須在任何 widget 建立之前執行)
if st.session_state.pop("pending_reset", False):
    clear_user_session()

if "pending_toast" in st.session_state:
    st.toast(st.session_state.pending_toast)
    del st.session_state.pending_toast

# Visual-polish pass, item 2: the top status strip (#gp-status-strip, further
# down) renders only on the Generator view (render_progress_strip()'s own
# guard), so only Generator's copy of the shared stMainBlockContainer rule
# below needs the extra headroom that clears it - see the comment on that
# rule for the arithmetic and for why this is a container-wide padding
# rather than a spacer element. st.session_state.active_view is already set
# by this point (session init near the top of this file), and every nav
# click that changes it calls st.rerun() before any more render code runs,
# so this always reflects the view actually being drawn this run, regardless
# of where in the script it is read from.
main_container_padding_top = (
    "5.75rem" if st.session_state.active_view == workspace.GENERATOR else "3.25rem"
)

# Lightweight visual system: native CSS only, no UI/animation framework.
# Sidebar width is locked from CSS rather than left to Streamlit's own
# resizable wrapper. Read off the live DOM: Streamlit writes the width as an
# INLINE style on [data-testid="stSidebar"] (`width: 300px`, alongside the
# `user-select`/`position: relative` signature of a re-resizable wrapper) and
# its drag handle rewrites that inline value. A CSS `!important` width beats an
# inline declaration, so pinning it here makes dragging a no-op without having
# to target the handle's volatile emotion-hash class at all. The owner asked
# for exactly one control - a collapse button - and no width dragging.
SIDEBAR_EXPANDED_PX = 300

# The collapsed rail is 96px of *visible* sidebar - the same w-24 the owner's
# reference app uses (Dashboard.tsx:67).
#
# Getting there needs a trick, because Streamlit clamps the sidebar section to
# a 200px floor from JS rather than CSS: probed in a live browser, a stylesheet
# !important, a higher-specificity selector, and even an inline
# style.setProperty(..., "important") all left getComputedStyle reporting
# min-width: 200px, because React owns that attribute and rewrites it.
#
# So the section stays at its 200px floor and is slid left by the difference,
# hanging the surplus off the left edge of the viewport; the content is padded
# by the same amount so the icons land inside the strip that is still visible.
# Flex layout accounts for the negative margin, so the main content column
# follows to ~108px instead of staying at 200. Verified in the browser:
# section 200px wide, left -104, right 96, main content left 108.
SIDEBAR_RAIL_PX = 96
# The section's real width, which no CSS this app writes can change - measured
# rather than assumed. A `width: !important` is ignored exactly like the
# min-width above, so the <section> stays at Streamlit's own 300px in both
# states and the slide below has to be computed against 300, not against the
# 200px min-width floor. (Getting this wrong left the rail 196px wide with its
# icons centred for 96 - visibly lopsided.)
SIDEBAR_RAIL_FLOOR_PX = SIDEBAR_EXPANDED_PX
SIDEBAR_RAIL_OFFSET_PX = SIDEBAR_RAIL_FLOOR_PX - SIDEBAR_RAIL_PX
# Side of the square icon tiles, and the basis for centring them on the rail.
SIDEBAR_RAIL_ICON_PX = 52

_SIDEBAR_WIDTH_CSS = """
    /* Both the <section> and its inner content div carry the width; pinning
       only one leaves the other free to disagree during a drag. */
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > [data-testid="stSidebarContent"] {
        width: %(w)dpx !important;
        min-width: %(w)dpx !important;
        max-width: %(w)dpx !important;
    }

    /* Streamlit's own collapse button hides the sidebar outright. The owner
       wants it to shrink to an icon rail instead, so the native control is
       removed and replaced by the one rendered inside the sidebar itself. */
    [data-testid="stSidebarCollapseButton"] { display: none !important; }

    /* The toggle straddles the sidebar's right edge as a circular chip, the
       way the owner's reference app does it
       (Dashboard.tsx:71 - `absolute -right-3.5 top-8 rounded-full`, revealed
       on sidebar hover). Streamlit renders the button in normal flow, so it
       is lifted out with position:absolute; the sidebar <section> already
       carries position:relative from Streamlit's own inline style, which is
       what this anchors against.

       overflow must stay visible on the ancestors or a chip hanging 14px past
       the edge gets clipped. */
    /* The sidebar must scroll. An earlier version set `overflow: visible` on
       both the section and its content so the collapse chip could hang 14px
       past the right edge - which also killed scrolling, hiding the Settings
       expander and the whole login form below the fold. Scrolling wins; the
       chip is tucked just inside the edge instead (see its `right` below).
       Note CSS cannot split the axes here: setting overflow-x: visible with
       overflow-y: auto silently computes the x axis to auto as well. */
    [data-testid="stSidebar"] > [data-testid="stSidebarContent"] {
        overflow-y: auto !important;
    }

    [data-testid="stSidebar"] .st-key-sidebar_toggle {
        position: absolute !important;
        top: 2rem;
        right: 6px;
        width: auto !important;
        z-index: 30;
        opacity: 0;
        transition: opacity var(--ease), transform var(--ease);
    }

    /* Revealed on hover, and always while focused so it stays keyboard
       reachable - the reference's pure opacity-0 would strand keyboard users. */
    [data-testid="stSidebar"]:hover .st-key-sidebar_toggle,
    [data-testid="stSidebar"] .st-key-sidebar_toggle:focus-within {
        opacity: 1;
    }

    [data-testid="stSidebar"] .st-key-sidebar_toggle button {
        width: 28px !important;
        height: 28px !important;
        min-height: 28px !important;
        padding: 0 !important;
        border-radius: 999px !important;
        background: var(--surface) !important;
        border: 1px solid var(--border) !important;
        box-shadow: var(--shadow-sm) !important;
        color: var(--muted) !important;
    }

    [data-testid="stSidebar"] .st-key-sidebar_toggle button:hover {
        color: var(--brand) !important;
        transform: scale(1.1);
    }
"""

_SIDEBAR_RAIL_CSS = """
    /* Collapsed rail. Modelled on the owner's own reference app, whose
       MobileNavItem stacks the icon above a 10px label and centres both
       (frontend/src/components/Dashboard.tsx) - rather than hiding the label
       outright. That matters here because Streamlit will not let the sidebar
       go below 200px: an icon-only column inside a 200px shell leaves a wide
       dead margin and reads as broken, which is exactly the "太扁" the owner
       reported. Keeping a small centred label makes 200px look deliberate.

       Streamlit renders the icon and the label as siblings inside the button
       ([data-testid="stIconMaterial"] and [data-testid="stMarkdownContainer"],
       confirmed against the live DOM), so column-stacking their shared parent
       is all this needs - no bespoke button markup. */
    /* Icons only - no labels at all, matching the rail the owner sketched:
       a stack of outline icons, the active one a filled navy square, generous
       vertical rhythm, dividers between groups. */
    [data-testid="stSidebar"] [class*="st-key-nav_"] button [data-testid="stMarkdownContainer"] {
        display: none !important;
    }

    /* Scoped to the nav buttons only. Scoping this to every .stButton in the
       sidebar also caught the collapse toggle, inflating it from its 28px
       circle to a 52px square that hung past the rail's edge - the owner saw
       that as "收折前後大小不一樣". */
    [data-testid="stSidebar"] [class*="st-key-nav_"] button {
        justify-content: center !important;
        width: 52px !important;
        height: 52px !important;
        min-height: 52px !important;
        padding: 0 !important;
        /* auto side margins, not just the bottom one: the button sits inside a
           full-width stElementContainer, so without them a 52px tile pins to
           the left of a 96px rail (measured centre 26 against a rail centre of
           48). align-items on the vertical block does not reach it - that
           centres the containers, which are already full width. */
        margin: 0 auto 0.75rem auto !important;
        border-radius: 14px !important;
    }

    [data-testid="stSidebar"] [class*="st-key-nav_"] button [data-testid="stIconMaterial"] {
        font-size: 24px !important;
    }

    /* Monogram stays, centred on the rail - the reference keeps its "G" tile
       at the top of the collapsed sidebar. */
    [data-testid="stSidebar"] .sb-logo {
        margin-left: auto !important;
        margin-right: auto !important;
    }

    [data-testid="stSidebar"] .sb-brand {
        justify-content: center !important;
        /* The wordmark is display:none, but .sb-brand's row gap still counts
           against the flex line, pushing the monogram half a gap off centre
           (measured: centre 38 against a rail centre of 48). */
        gap: 0 !important;
    }

    /* Chrome that carries no meaning at rail width: the wordmark beside the
       monogram, the group labels, and the whole signed-out auth block. The
       nav itself and the account avatar stay - the owner asked for the rail
       to keep showing things, not to empty out. */
    [data-testid="stSidebar"] .sb-micro-label,
    [data-testid="stSidebar"] .sb-wordmark,
    [data-testid="stSidebar"] .sb-account-text,
    [data-testid="stSidebar"] [data-testid="stForm"],
    [data-testid="stSidebar"] [data-testid="stRadio"],
    [data-testid="stSidebar"] [data-testid="stExpander"],
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        display: none !important;
    }
"""


_SIDEBAR_RAIL_SLIDE_CSS = """
    /* Slide the surplus off-screen so only SIDEBAR_RAIL_PX stays visible. See
       the constants' comment for why the section itself cannot simply be made
       narrower. */
    [data-testid="stSidebar"] {
        margin-left: -%(off)dpx !important;
    }

    [data-testid="stSidebar"] > [data-testid="stSidebarContent"] {
        padding-left: %(off)dpx !important;
    }

    /* Centre the rail's contents by letting the content box keep the rail's
       full width and centring children inside it - NOT by padding the box down
       to icon width. Padding it symmetrically was the previous attempt and it
       is what made the rail look crooked: it left a 32px box that both the
       52px icon tiles and the 38px monogram overflowed, by different amounts,
       so their centres landed 10px apart (48 vs 38). A column flex with
       align-items:center centres every child on the same line regardless of
       its own width. */
    /* Two things are needed, and neither is align-items.

       1. The content box must actually span the rail. Streamlit leaves ~20px
          of right padding on the sidebar content, so the box measured 76px
          inside a 96px rail - everything centred in it landed on 38 instead of
          48, which is the crookedness the owner kept seeing.

       2. The button must be centred as an INLINE-level box. Streamlit renders
          it display:inline-flex, and `margin: 0 auto` does nothing on an
          inline-level element (computed marginLeft came back 0px). text-align
          on its block parent is what actually moves it. */
    [data-testid="stSidebar"] > [data-testid="stSidebarContent"] {
        padding-right: 0 !important;
    }

    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {
        padding-right: 0 !important;
    }

    [data-testid="stSidebar"] [class*="st-key-nav_"],
    [data-testid="stSidebar"] [class*="st-key-nav_"] [data-testid="stButton"],
    [data-testid="stSidebar"] .sb-brand {
        text-align: center !important;
    }
"""


def _sidebar_css():
    collapsed = st.session_state.get("sidebar_collapsed", False)
    width = SIDEBAR_RAIL_FLOOR_PX if collapsed else SIDEBAR_EXPANDED_PX
    css = _SIDEBAR_WIDTH_CSS % {"w": width}
    if collapsed:
        css += _SIDEBAR_RAIL_SLIDE_CSS % {"off": SIDEBAR_RAIL_OFFSET_PX}
        css += _SIDEBAR_RAIL_CSS
    return css


st.markdown(("<style>\n" + css_root_block() + _sidebar_css() + """

    html, body, [data-testid="stAppViewContainer"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: var(--bg);
        color: var(--text);
    }

    /* Renamed from .main .block-container; the old selector matched nothing
       after the 1.6x DOM change, so the width cap was silently not applied. */
    [data-testid="stMainBlockContainer"] {
        /* Base value: 3.25rem, same as before the top status strip existed.
           This is what Career Profile and Tracker actually render with -
           neither ever shows the strip, so neither needs more.

           Generator needs more (see main_container_padding_top, computed in
           Python just above this block, before this string is built): the
           strip sits flush at top:3.75rem (Streamlit's own toolbar height -
           see the #gp-status-strip rule below for that constant's source)
           with no gap of its own, above "pinned to the very top of the page"
           left no room for one. Its own box is 0.35rem padding top + 0.35rem
           padding bottom (0.7rem) plus its content row - a 4px/0.25rem
           progress track sitting behind a 0.7rem-line-height label, so the
           label (the taller of the two) sets the row height at roughly
           1rem once its font's own ascent/descent is included. 3.75 + 0.7 +
           1 = 5.45rem to clear the strip exactly, plus 0.3rem of breathing
           room before content starts = 5.75rem. (This replaced a pill-
           shaped bar that needed 9.5rem - the whole point of item 2 was
           that the strip takes "essentially no vertical space", and this
           number is the proof: less than half the old headroom.)

           This has to stay a padding-top on the whole container, not a
           spacer element scoped to the Generator branch: render_result_banner()
           (below) runs before the per-view dispatch, so on the Generator view
           it can render at the very top of this same container, ahead of
           anything a spacer placed inside the Generator branch could push
           down. A container-wide padding-top clears it too, regardless of
           render order - which is also why the Generator-vs-not decision has
           to happen in Python before this string is built, rather than
           through some DOM-order-dependent trick. */
        padding-top: """ + main_container_padding_top + """;
        /* Task 4 density pass: 3rem -> 2rem. padding-top is untouched - it is
           pinned to the headroom arithmetic explained above and guarded by
           tests/test_floating_progress.py's
           test_main_container_padding_is_pinned (the Generator value) and
           tests/test_app_smoke.py's test_density_pass_css_values_are_pinned
           (the shared base value). */
        padding-bottom: 2rem;
        max-width: 1320px;
    }

    /* Task 4 density pass ("畫面太空白" / 全域縮小間距與內邊距, design doc):
       Streamlit's default gap between stacked/side-by-side elements is 1rem
       ("small", the gap= default streamlit.elements.layouts documents for
       every st.container/st.columns call in this file - confirmed by
       reading that module's docstring directly). Tightened once here rather
       than passing gap= to every one of this file's container/columns call
       sites individually. Applies to every view, not just Generator: this
       selector is not scoped to any single container, so it also tightens
       Career Profile's stacked form cards and Tracker's dashboard, matching
       the "touches every view" scope of this pass. !important for the same
       reason several rules below already needed it - no local way to check
       whether Streamlit's own gap styling is inline or class-based in this
       version, so this beats either. */
    /* Breathing room between blocks. The Task 4 density pass pulled this to
       0.6rem to fill an empty-looking screen; with the page now full, that
       same value reads as cramped. This is the reversal, done deliberately. */
    [data-testid="stVerticalBlock"] {
        gap: 1.35rem !important;
    }

    [data-testid="stHorizontalBlock"] {
        gap: 0.75rem !important;
    }

    [data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
        font-size: 1.1rem;
        line-height: 1.3;
        margin-bottom: 0.35rem;
    }

    /* Task 4 density pass, corrected in the UI final-review fix wave
       (Important 3): a bare `h1, h2, h3, h4 { margin-top/bottom }` selector
       never applied. Confirmed by grepping the shipped streamlit==1.61.1
       bundle (StreamlitMarkdown.<hash>.js): Streamlit puts its own
       "h1, h2, h3, h4, h5, h6": {margin: 0} rule on an emotion class on the
       stMarkdownContainer div nested inside stHeading, i.e. a compound
       selector like `.cssHash h1` at specificity (0,1,1) - which always beat
       a bare `h1` at (0,0,1), so the margin-top/bottom below were dead code.
       Worse, Streamlit's own heading spacing is padding, not margin (same
       bundle: h1 padding is spacing.xl 0 spacing.lg 0, h2 is lg 0 lg 0, h3 is
       md 0 lg 0, h4 is sm 0 lg 0) - so even a winning margin rule would have
       ADDED space on top of that padding instead of tightening it.
       [data-testid="stHeading"] h1 matches Streamlit's own (0,1,1)
       specificity exactly (an attribute selector counts the same as a class),
       so plain cascade order (this stylesheet renders after Streamlit's own
       initial styles) should be enough on its own - but unlike Streamlit's
       base styles, which load once up front, this order isn't guaranteed the
       same way for every rerun, so !important removes the "should" the same
       way the two gap rules above already do. */
    /* Visual-polish pass, item 4 (typography), corrected in the visual-match
       follow-up (Item 3): every actual <hN> in the reference - not just
       icons/buttons, which do use --color-primary - is near-black, not navy.
       Confirmed by reading every heading tag in ResumeBuilder.tsx/Dashboard.tsx:
       the one h2 page title ("Resume Generator", ResumeBuilder.tsx:368) is
       `text-slate-950` (#020617, exactly TOKENS["navy-dark"]); every h3/h4
       section heading actually used ("Target & Strategy" :395, "Generate
       Preview" :458, "Professional Preview" :537, "Draft Table" :655,
       "Source of Truth" h4 :378, Dashboard.tsx's pricing h2/h3 :272,:299) is
       `text-gray-900` (#111827, exactly TOKENS["text"]) - `text-primary`
       never appears on a heading tag itself in either file, only on icons and
       buttons next to them. This app never calls st.title/st.header (grepped
       app.py - zero hits), so h3 (st.subheader) and h4 (st.markdown "####")
       are the only levels actually reachable; h1/h2 are corrected too, for
       when/if this app ever grows one, but that half is unverified in this
       app today. Weight follows the same source: font-bold (700) on every
       h3/h4 above, font-extrabold (800) on the one h2. Line-height/spacing
       unchanged - Streamlit's own heading rule sets those explicitly on a
       same-specificity compound selector, so plain cascade order is not
       something to rely on for them either, same as the padding rule above. */
    [data-testid="stHeading"] h1,
    [data-testid="stHeading"] h2 {
        color: var(--navy-dark);
        font-weight: 800 !important;
    }

    [data-testid="stHeading"] h3,
    [data-testid="stHeading"] h4 {
        color: var(--text);
        font-weight: 700 !important;
    }

    [data-testid="stHeading"] h1,
    [data-testid="stHeading"] h2,
    [data-testid="stHeading"] h3,
    [data-testid="stHeading"] h4 {
        letter-spacing: -0.01em;
        line-height: 1.25 !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        margin-bottom: 0.35rem !important;
    }

    /* One deliberate scale instead of Streamlit's defaults, which had
       "Export Settings" rendering roughly twice the size of "Source of Truth"
       purely because one is a subheader and the other a markdown bold. */
    [data-testid="stHeading"] h1 { font-size: 1.5rem !important; }
    [data-testid="stHeading"] h2 { font-size: 1.2rem !important; }
    [data-testid="stHeading"] h3 { font-size: 1.05rem !important; }
    [data-testid="stHeading"] h4 { font-size: 0.95rem !important; }

    /* The description under a heading: smaller, muted, and given room before
       whatever follows, so the pair reads as one unit rather than three lines
       of equal weight. */
    [data-testid="stHeading"] + [data-testid="stElementContainer"] [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] {
        font-size: 0.85rem !important;
        color: var(--muted) !important;
        line-height: 1.55 !important;
        margin-bottom: 0.5rem !important;
    }

    /* Visual-polish pass, item 4: every plain widget label (st.text_input,
       st.text_area, st.selectbox, st.multiselect, ...) becomes an uppercase,
       letter-spaced micro-label - the same recipe .sb-micro-label already
       uses in the sidebar (further down), now applied through Streamlit's
       own stWidgetLabel wrapper instead of being copy-pasted under a second
       selector. Targets the wrapper itself, not a guessed inner tag: every
       property below is inheritable, so it reaches whatever nested
       span/p Streamlit puts the label text in without this rule needing to
       know that structure. This is what turns "Job description" into
       "JOB DESCRIPTION" (the reference design's own example) with no
       per-field changes anywhere in this file.

       Deliberately does not reach st.data_editor's own column_config labels
       (e.g. "School" on the Education table, Career Profile view) -
       glide-data-grid paints those onto a <canvas>, not real DOM text, so
       CSS cannot touch them regardless of selector (confirmed against the
       streamlit==1.61.1 frontend bundle, which never emits a stWidgetLabel
       node for a column_config label). Also deliberately does not reach the
       "Custom Strategy" st.expander's own header text (render_generator_
       workspace, below) - Streamlit gives expander headers no data-testid
       of their own to anchor on, and this app has several other expanders
       (Manual Result Import, Advanced Optimized JSON Import, Settings, ...)
       whose titles are still meant to read as normal clickable controls;
       uppercasing every expander header along with it was judged a worse
       trade than leaving that one label as plain text. The field *inside*
       that expander is a normal st.text_area labelled "Custom Strategy" (no
       label_visibility="collapsed" - it used to be collapsed, under the
       plainer label "Strategy"), so this rule reaches that one exactly like
       any other field label and does turn it into "CUSTOM STRATEGY" - the
       reference design's own second example, alongside "Job description"
       just above it. Only the expander's own clickable header text is out
       of reach, not the field inside it. */
    [data-testid="stWidgetLabel"] {
        font-size: 0.66rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        color: var(--muted) !important;
    }

    p, label, [data-testid="stCaptionContainer"] {
        color: var(--muted);
    }

    /* st.container(border=True) used to be an inline-styled div we could hook;
       Streamlit now paints the border itself on stVerticalBlock via a hashed
       emotion class. Nothing left to target that would not break again on the
       next release, so the native card styling stands. */

    .stButton button,
    .stDownloadButton button,
    .stFormSubmitButton button,
    input,
    textarea {
        transition: background-color var(--ease), border-color var(--ease), box-shadow var(--ease), color var(--ease), transform var(--ease) !important;
    }

    /* Visual-polish pass, item 5: secondary buttons (the default kind - most
       buttons in this app) go from a visible 1px hairline border on a plain
       white surface to borderless-with-a-subtle-fill, matching the reference
       design ("nearly borderless ... a subtle background instead"). Primary
       buttons (kind="primary") get their own rule further down: solid
       filled --navy, no border. Extended to .stFormSubmitButton here (it
       was previously only in the p/span colour-inherit rule below, so the
       Login/Create Account buttons - the only two form_submit_buttons in
       this app - were relying on Streamlit's unstyled default box). */
    .stButton button,
    .stDownloadButton button,
    .stFormSubmitButton button {
        border-radius: var(--radius) !important;
        min-height: 42px !important;
        font-weight: 650 !important;
        /* A visible edge, not a transparent one. Measured in the browser: the
           label was already 16.19:1 against the old fill, so "看不到字" was
           never a text-contrast problem - it was that a borderless #f1f5f9
           fill on an #f8fafc page has no edge at all, so the control does not
           read as a button. The reference app's secondary is
           `bg-white border border-gray-200` (ResumeBuilder.tsx:424). */
        border: 1px solid var(--border) !important;
        background: var(--surface) !important;
        color: var(--text) !important;
        box-shadow: var(--shadow-sm);
    }

    /* Descendant, not child: a button with help= is wrapped in a tooltip span,
       which pushed it out of `.stButton > button` and left its label painted
       with the muted body colour - grey text on a blue primary button. */
    .stButton button p,
    .stButton button span,
    .stDownloadButton button p,
    .stFormSubmitButton button p {
        color: inherit !important;
    }

    .stButton button:hover,
    .stDownloadButton button:hover,
    .stFormSubmitButton button:hover {
        /* Reference: `hover:border-primary hover:text-primary`. */
        border-color: var(--navy) !important;
        color: var(--navy) !important;
        box-shadow: var(--shadow-md);
        transform: translateY(-1px);
    }

    /* Primary buttons: solid filled --navy, no border - the reference
       design's primary-action colour (distinct from --brand, which stays in
       use everywhere else - see TOKENS's own comment in theme.py). This is
       also, mechanically, the active WORKSPACE nav pill: nav buttons render
       type="primary" for whichever view is current (`with st.sidebar:`,
       further down), so it inherits this same rule rather than needing a
       separate one. */
    .stButton button[kind^="primary"],
    .stDownloadButton button[kind^="primary"],
    .stFormSubmitButton button[kind^="primary"] {
        background: var(--navy) !important;
        border-color: var(--navy) !important;
        /* TOKENS has no dedicated "on-dark text" token, but --surface is
           already the exact colour this needs (#ffffff) - reused by value
           rather than adding a second token that would only ever equal the
           first, so this still flows through TOKENS/css_root_block() like
           every other colour in this block instead of a hardcoded literal. */
        color: var(--surface) !important;
    }

    .stButton button[kind^="primary"]:hover,
    .stDownloadButton button[kind^="primary"]:hover,
    .stFormSubmitButton button[kind^="primary"]:hover {
        background: var(--navy-dark) !important;
        border-color: var(--navy-dark) !important;
    }

    /* Streamlit dropped BaseWeb entirely, so every data-baseweb hook is gone. */
    .stButton button:focus-visible,
    .stDownloadButton button:focus-visible,
    .stFormSubmitButton button:focus-visible,
    input:focus,
    textarea:focus {
        outline: none !important;
        border-color: var(--brand) !important;
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18) !important;
    }

    input,
    textarea {
        border-radius: var(--radius) !important;
        border-color: var(--border) !important;
        background: var(--surface) !important;
    }

    textarea {
        line-height: 1.55 !important;
    }

    /* Item 2 (typography): the JD / Custom Strategy fields specifically -
       owner said this block's type was badly sized. Reference recipe
       (ResumeBuilder.tsx:396-419, both fields share one className): `mt-1.5
       w-full bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm
       focus:outline-none focus:ring-2 focus:ring-primary/10`. rounded-lg
       (8px) and border-gray-200 (#E5E7EB, near-identical to var(--border)
       #e2e8f0) were already covered by the generic input/textarea rule just
       above; what was missing is bg-gray-50 (a light fill, not the plain
       white every other textarea gets) and p-4/text-sm (generous 1rem
       padding and 0.875rem body text, instead of Streamlit's own tighter
       default). var(--surface-soft) (#f1f5f9) stands in for bg-gray-50
       (#F9FAFB) - both light neutral fills, and already an existing TOKENS
       entry rather than a new literal.
       Scoped to just these two fields, not every textarea in the app (the
       Summary/About Me/Cover Letter/manual-JSON-import fields keep the
       plain white background) via the `st-key-jd_input_<n>` /
       `st-key-cp_input_<n>` class Streamlit's key= emits - same substring-
       match pattern the [class*="st-key-tr"] rule below already relies on -
       because both keys carry a `base_editor_key` suffix that increments on
       every profile edit/import, so only the stable prefix can be matched.
       The micro-label above these fields (JOB DESCRIPTION / CUSTOM STRATEGY)
       is deliberately left on the shared [data-testid="stWidgetLabel"] rule
       above rather than duplicated here: reference values there are close
       but not identical (text-xs/font-extrabold/tracking-widest/#9CA3AF vs.
       this rule's 0.66rem/700/0.08em/var(--muted)) - visually close, but
       changing it would restyle every widget label in the app, not just
       these two, so it was left alone rather than guessed at. */
    [class*="st-key-jd_input_"] textarea,
    [class*="st-key-cp_input_"] textarea {
        background: var(--surface-soft) !important;
        padding: 1rem !important;
        font-size: 0.875rem !important;
    }

    hr {
        border-color: var(--border);
        /* Task 4 density pass: 1.1rem -> 0.75rem. */
        margin: 0.75rem 0;
    }

    /* st.container(border=True) - the cards that hold Source of Truth, Export
       Settings and the rest. Streamlit's own padding sits tight against the
       frame; the owner asked for the frame to stand further off its contents,
       so this sets it explicitly rather than inheriting.
       Radius corrected in the visual-match follow-up (Item 3): every card
       variant in the reference - the Draft Table wrapper (ResumeBuilder.tsx
       :656), the Professional Preview panel (:548), the per-block skill card
       (:797), Source of Truth (:372) - uses `rounded-lg`, Tailwind's 0.5rem
       (8px), never a larger radius; the 12px this used to hard-code had no
       reference number behind it. var(--radius) is already 8px
       (theme.css_root_block()), so this now just defers to that token
       instead of overriding it, which is also what "TOKENS for all colours"
       (this is the one non-colour token css_root_block() also defines)
       already intends every other radius in this stylesheet to do.
       Padding (1.5rem 1.6rem, below) is deliberately left alone: the
       reference has no single equivalent to copy - its cards range from
       p-3.5 (14px) to p-12 (48px) depending on which one - and this app's
       st.container(border=True) is reused for many sections the reference
       renders with different, unrelated recipes, so no single number from it
       would be "the" match either. */
    [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {
        border-radius: var(--radius) !important;
    }

    [data-testid="stVerticalBlockBorderWrapper"] > div {
        padding: 1.5rem 1.6rem !important;
    }

    /* The preview's Resume / Cover Letter switch must never stack. Measured at
       the default split: the group's box is 185px and its two options need
       186px, so any drag that narrows the preview tips it into wrapping - the
       two options land on separate lines and the control stops reading as one
       switch. Keeping the row nowrap and letting the options give up their
       side padding degrades gracefully instead. */
    [class*="st-key-tr"] [data-testid="stButtonGroup"] {
        display: flex !important;
        flex-wrap: nowrap !important;
    }

    [class*="st-key-tr"] [data-testid="stButtonGroup"] button {
        flex: 0 1 auto !important;
        min-width: 0 !important;
        white-space: nowrap !important;
        padding-left: 0.55rem !important;
        padding-right: 0.55rem !important;
    }

    [data-testid="stAlert"] {
        border-radius: var(--radius);
        border: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
        /* Task 4 density pass: previously unset (Streamlit's own default);
           set explicitly, matching the tightened stMetric padding below. */
        padding: 0.75rem 1rem;
    }

    [data-testid="stMetric"] {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        /* Roomier than the Task 4 density pass (0.6rem 0.85rem) - the owner
           wants the frame further from its contents. */
        padding: 1.25rem 1.4rem;
        box-shadow: var(--shadow-sm);
    }

    /* base_preview_pdf's show_spinner (app.py, near generate_preview_pdf_bytes)
       only ever fires on a genuine cache miss - see that function's own
       docstring for why. .stCacheSpinner is the class Streamlit adds only to
       a cache-triggered spinner (the `cache=True` prop on its Spinner proto,
       confirmed by reading the frontend's Spinner component source), so this
       cannot also restyle the unrelated "Generating..." spinner in
       render_export_settings() - deliberately: that one is out of scope for
       this task. Brand colour cascades to the icon via `color: inherit`
       (confirmed by reading DynamicIcon's source), so one rule recolours
       both the icon and the text. */
    [data-testid="stSpinner"].stCacheSpinner {
        color: var(--brand) !important;
    }

    /* Blue while an AI call is in flight, green once it lands (below). Both use
       the .st-key- hook that ui_feedback.py and render_result_banner set up. */
    .st-key-ai_status details,
    .st-key-ai_status [data-testid="stExpander"] {
        border-left: 4px solid var(--brand) !important;
        background: rgba(37, 99, 235, 0.05) !important;
        border-radius: var(--radius) !important;
    }

    .st-key-ai_status [data-testid="stMarkdownContainer"] p {
        color: var(--text);
        font-size: 0.92rem;
    }

    /* st.container(key="result_banner") emits .st-key-result_banner. This is a
       documented hook, unlike the hashed emotion classes, so it is safe to
       target. Green accent marks it as an outcome rather than another form. */
    .st-key-result_banner {
        border-color: rgba(5, 150, 105, 0.35) !important;
        border-left: 4px solid var(--success) !important;
        background: rgba(5, 150, 105, 0.06) !important;
    }

    .st-key-result_banner p {
        color: var(--text);
    }

    .st-key-dismiss_result_banner button {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        color: var(--muted) !important;
        min-height: 28px !important;
    }

    /* Editing a LaTeX resume is a desktop task, and the multi-column layouts
       plus fixed-height iframes below do not survive a phone. Say so instead of
       letting the user discover it. */
    #small-screen-notice {
        display: none;
        margin: 0 0 1rem 0;
        padding: 0.75rem 1rem;
        border: 1px solid var(--warning);
        border-radius: var(--radius);
        background: rgba(217, 119, 6, 0.08);
        color: var(--warning);
        font-size: 0.9rem;
        font-weight: 650;
    }

    @media (max-width: 900px) {
        #small-screen-notice { display: block; }
    }

    /* Visual-polish pass, item 2: thin top status strip - rendered only on
       the Generator view, by render_progress_strip() below. Replaces the
       old floating pill (#gp-floating-progress, position:fixed, centred,
       ~4.3rem tall, pill-radius'd) with a full-width hairline strip pinned
       flush under Streamlit's own toolbar, "taking essentially no vertical
       space" per the owner's own framing - see the arithmetic on the
       stMainBlockContainer padding-top rule above for exactly how little.
       The walking figure (theme.walker_svg(), still used by ui_feedback.
       run_ai_call()'s panel, further below) does not appear here: a
       recognisable walking figure does not compress into a hairline row
       without either dominating its height or reading as an illegible
       smudge at the size that would leave it, and the task's own
       instruction was explicit that dropping it is the correct call in
       that case ("drop the figure rather than fattening the strip") - so
       this keeps only the fill bar, the per-stage stop dots, and the status
       label. Self-contained under our own #gp-/.gp- names; nothing here
       targets a Streamlit-internal class, so a platform upgrade cannot
       break it the way the old ".main .block-container" selector above
       once did. */
    /* "New application" rides the status strip so it is reachable at any
       moment, not just after scrolling back up. Fixed-positioned onto the
       strip's right end (strip is z-index 999, this sits just above it) and
       its now-empty flow container is collapsed so it leaves no gap.
       Same `top` as the strip, so the two share a row. */
    [class*="st-key-new_application"] {
        position: fixed !important;
        top: 3.75rem;
        right: 1rem;
        width: auto !important;
        z-index: 1000;
        margin: 0 !important;
    }

    [class*="st-key-new_application"] button {
        min-height: 30px !important;
        padding: 0.1rem 0.7rem !important;
        font-size: 0.78rem !important;
        border-radius: 999px !important;
    }

    #gp-status-strip {
        position: fixed;
        /* Streamlit's real toolbar height is 3.75rem (theme.sizes.headerHeight
           in the streamlit==1.61.1 frontend bundle - confirmed by grepping the
           shipped JS: the header's own styled-component sets
           height/minHeight:e.sizes.headerHeight, and Streamlit's own toast
           container docks fixed elements at top:e.sizes.headerHeight, the
           same pattern used here. 2.875rem is a different constant
           (fullScreenHeaderHeight) used only for an individual element's
           fullscreen view, not the app toolbar - using it would sit this
           strip under the toolbar instead of below it.) Flush against that
           edge, no extra offset - "pinned to the very top of the page"
           left no room for one the way the old pill's own +0.75rem gap
           had. */
        top: 3.75rem;
        /* Starts at the sidebar's right edge, not at 0. Measured in the
           browser: with left:0 the strip ran 0→1440 at z-index 999 while the
           sidebar occupies 0→300 at z-index 999991, so the sidebar painted
           over the strip's leftmost 300px - the owner's "被 side bar 擋住".
           Raising the strip's z-index instead would put it *over* the
           sidebar, which is worse. The offset is interpolated from the same
           Python constant that sets the sidebar width, so it tracks the
           collapse state automatically instead of hard-coding 300. */
        left: __SIDEBAR_W__px;
        right: 0;
        z-index: 999;
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.35rem 1.25rem;
        background: var(--surface);
        border-bottom: 1px solid var(--border);
    }

    .gp-strip-track {
        position: relative;
        flex: 1;
        height: 4px;
    }

    .gp-strip-track::before {
        content: "";
        position: absolute;
        left: 0;
        right: 0;
        top: 0;
        height: 4px;
        border-radius: 999px;
        background: var(--border);
    }

    .gp-strip-fill {
        position: absolute;
        left: 0;
        top: 0;
        height: 4px;
        border-radius: 999px;
        background: var(--brand);
        transition: width 420ms ease-in-out;
    }

    .gp-strip-stop {
        position: absolute;
        top: 2px;
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--surface);
        border: 2px solid var(--muted);
        transform: translate(-50%, -50%);
    }

    .gp-strip-stop-done {
        border-color: var(--success);
        background: var(--success);
    }

    .gp-strip-label {
        flex: none;
        font-size: 0.7rem;
        font-weight: 650;
        color: var(--muted);
        white-space: nowrap;
    }

    .gp-walker {
        display: block;
        width: 20px;
        height: 24px;
    }

    /* Compact generation-status panel (ui_feedback.run_ai_call, Task 4): the
       .gp-walker figure marching in place (no `left` to drive here - a
       single blocking call has no horizontal "progress" of its own) beside
       the current milestone message. Reuses .gp-walker/.gp-bob/.gp-legs/
       .gp-legs2 and their keyframes as-is; this is only the row layout that
       did not exist yet. This is the figure's only remaining use in the app
       - see the #gp-status-strip comment above for why the top strip itself
       does not also show it. */
    .gp-status-line {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .gp-status-line .gp-walker {
        flex: none;
    }

    .gp-status-line span {
        color: var(--text);
        font-size: 0.92rem;
    }

    /* Item 4: Optimize Resume's in-flight state (ui_feedback.run_ai_call()'s
       `target` path - see that function's own docstring for the full
       rationale). Same footprint as the primary button it replaces
       (min-height, radius, filled navy - matching the `.stButton button
       [kind^="primary"]` rule above) so the swap reads as the same control
       changing state, not a different element appearing - the button's own
       row becomes the status row, nothing is added below it. */
    .gp-btn-status {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        min-height: 42px;
        width: 100%;
        border-radius: var(--radius);
        background: var(--navy);
        box-sizing: border-box;
        padding: 0 1rem;
    }

    .gp-btn-status .gp-walker {
        flex: none;
    }

    .gp-btn-status span {
        color: var(--surface);
        font-weight: 650;
        font-size: 0.92rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    /* Walk cycle: two leg groups alternate via steps(), plus a slight bob.
       This keeps looping regardless of the walker's (state-driven) position -
       only `left` above is ever driven from Python. */
    .gp-bob { animation: gpbob .42s ease-in-out infinite alternate; }
    .gp-legs  { animation: gpstep  .42s steps(2,end) infinite; }
    .gp-legs2 { animation: gpstep2 .42s steps(2,end) infinite; }
    @keyframes gpstep  { 0%{opacity:1} 50%{opacity:0} }
    @keyframes gpstep2 { 0%{opacity:0} 50%{opacity:1} }
    @keyframes gpbob   { from{transform:translateY(0)} to{transform:translateY(-1.5px)} }

    /* Sidebar redesign: brand lockup, uppercase group micro-labels,
       recent-applications rows, and the bottom account block. Own `.sb-`
       prefix, the same convention `.gp-` above already uses, so neither can
       ever collide with a Streamlit-internal class name. All colour still
       comes from the :root variables at the top of this block (i.e. from
       TOKENS, via css_root_block()) - nothing here hard-codes a hex value. */
    .sb-brand {
        display: flex;
        align-items: center;
        gap: 0.65rem;
        padding: 0.2rem 0.1rem 0.6rem;
    }

    .sb-logo {
        flex: none;
        width: 38px;
        height: 38px;
        border-radius: var(--radius);
        background: var(--brand-dark);
        color: var(--surface);
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 0.95rem;
        letter-spacing: 0.02em;
    }

    .sb-wordmark-name {
        color: var(--text);
        font-weight: 750;
        font-size: 0.98rem;
        line-height: 1.18;
    }

    /* Shared by every uppercase group/section label in the sidebar: the
       brand block's "APPLICATION WORKSPACE", the "WORKSPACE" nav-group
       label, "RECENT APPLICATIONS", and the account block's
       "ACCOUNT · SETTINGS". */
    .sb-micro-label {
        font-size: 0.66rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin: 0.3rem 0 0.4rem 0.05rem;
    }

    .sb-brand .sb-micro-label,
    .sb-account .sb-micro-label {
        margin: 0.15rem 0 0;
    }

    .sb-hairline {
        border-color: var(--border);
        margin: 0 0 0.6rem;
    }

    /* Visual-polish pass, item 3: WORKSPACE nav buttons get the same
       explicit left padding and flex-start justification as the RECENT
       APPLICATIONS rows below (that rule's own padding is the other half of
       this pair - the two literals must stay equal). Neither this app's
       base .stButton rule nor Streamlit's own default pins a left padding
       for a plain button, so without both sides pinned to the identical
       value here, the icon + label in each group can drift to different
       left edges the next time either group's styling changes - which is
       exactly the "not flush left" the owner flagged. */
    [class*="st-key-nav_"] button {
        justify-content: flex-start !important;
        padding-left: 0.75rem !important;
    }

    /* Recent-applications rows (workspace.recent_applications()): lighter
       than the WORKSPACE nav buttons above them - these read as a list to
       scan, not as another set of primary actions. padding-left matches
       the nav-button rule above exactly (see its comment) so the status
       dot and company/role text line up under the same left edge as the
       nav icons and labels. */
    [class*="st-key-recent_app_"] button {
        min-height: 34px !important;
        padding: 0.3rem 0.6rem 0.3rem 0.75rem !important;
        border-color: transparent !important;
        background: transparent !important;
        box-shadow: none !important;
        font-weight: 500 !important;
        justify-content: flex-start !important;
        overflow: hidden !important;
    }

    [class*="st-key-recent_app_"] button:hover {
        background: var(--surface-soft) !important;
        border-color: var(--border) !important;
        box-shadow: none !important;
        transform: none !important;
    }

    /* Truncates the "Company — Role" label instead of wrapping or
       overflowing the sidebar - min-width:0 is needed because the label is
       a flex child (of the icon+label row Streamlit's own button markup
       builds) and would otherwise refuse to shrink below its text's natural
       width, which would silently defeat text-overflow:ellipsis below. */
    [class*="st-key-recent_app_"] button p {
        min-width: 0 !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
    }

    /* Status-dot colour: a fixed vocabulary of 5 token names
       (brand/warning/success/danger/muted - workspace.recent_applications()
       picks one per row) carried as a suffix on that row's own st.button
       key (recent_app_<index>_<token>). This stylesheet is injected before
       this session's Tracker data even exists, so it cannot know in advance
       which of up to 3 rows will need which colour - only the fixed set of
       colours a status could ever map to, which is what these 5 rules
       enumerate. Substring match, not exact class equality, because
       Streamlit may append its own class(es) after st-key-<key> on the same
       attribute. */
    [class*="st-key-recent_app_"][class*="_brand"] [data-testid="stIconMaterial"] { color: var(--brand) !important; }
    [class*="st-key-recent_app_"][class*="_warning"] [data-testid="stIconMaterial"] { color: var(--warning) !important; }
    [class*="st-key-recent_app_"][class*="_success"] [data-testid="stIconMaterial"] { color: var(--success) !important; }
    [class*="st-key-recent_app_"][class*="_danger"] [data-testid="stIconMaterial"] { color: var(--danger) !important; }
    [class*="st-key-recent_app_"][class*="_muted"] [data-testid="stIconMaterial"] { color: var(--muted) !important; }

    .sb-account {
        display: flex;
        align-items: center;
        gap: 0.55rem;
        padding: 0.15rem 0.1rem 0.3rem;
    }

    .sb-avatar {
        flex: none;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background: var(--surface-soft);
        border: 1px solid var(--border);
        color: var(--text);
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 0.82rem;
    }

    .sb-account-info {
        min-width: 0;
        flex: 1;
    }

    .sb-account-email {
        color: var(--text);
        font-weight: 650;
        font-size: 0.85rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    /* Visual-polish pass, item 6: two-tone Generator columns - white
       workspace (left) vs light blue-grey preview (right), TOKENS' own
       --surface and --bg, so the split reads visually even before the
       splitter handle (render_generator_splitter(), further down) is ever
       touched. Scoped with :has() to a zero-content marker container each
       column's own render function places first
       (st.container(key="gp_workspace_col") in render_generator_workspace,
       st.container(key="gp_preview_col") in render_preview) - not to
       [data-testid="stColumn"] position (first/last-of-type), which would
       also repaint every *other* two-column layout in the app (the
       Optimize/Copy Prompt button pair, the ATS metric/keyword columns, the
       Resume/Cover Letter switch, Career Profile's own field columns, ...).
       :has() with a descendant combinator (no `>`) tolerates whatever
       wrapper depth Streamlit puts between stColumn and the marker; this
       app already assumes a modern desktop browser (#small-screen-notice
       above), and :has() has shipped in every evergreen browser since
       2023, so no older-browser fallback is attempted. This is independent
       of the splitter script below (plain CSS, present on first paint, not
       waiting on any JS to run) - dragging only ever changes width, never
       colour, so the two are safe to keep decoupled. */
    /* The workspace side is white edge to edge - the owner wants grey only on
       the preview panel. Stretching it means the app background cannot show
       through below the content, which is where the stray grey band came
       from. */
    [data-testid="stColumn"]:has([data-gp-col="workspace"]) {
        background: var(--surface) !important;
        align-self: stretch !important;
        min-height: calc(100vh - 7rem);
        padding: 1.25rem 1.5rem 2rem 0 !important;
    }

    [data-testid="stColumn"]:has([data-gp-col="preview"]) {
        background: var(--bg) !important;
        border-left: 1px solid var(--border);
        padding: 1.25rem 1.25rem 2rem !important;
    }

    /* The preview stays in view while the left workspace scrolls. Both columns
       live in one scroll container, so without this the PDF scrolls away as
       soon as the editing side gets long - the owner reads that as the preview
       "not moving with" the page. Sticky keeps it pinned below the status
       strip instead. align-self is required: a stretched flex item has no
       spare room to slide within, so sticky would never engage.
       min-height matches the workspace column's own min-height (above) -
       align-self: flex-start means this column would otherwise only be as
       tall as whatever it holds, so a short empty-state message left the
       grey fill stopping partway down the page instead of reaching the
       bottom (Item 1: "右邊預覽就是全灰底" - the grey must be the *whole*
       column, not just a band behind the content). Same value as max-height
       just below, so the column is a fixed height regardless of content;
       overflow-y: auto still lets a genuinely taller PDF scroll inside it. */
    [data-testid="stColumn"]:has([data-gp-col="preview"]) {
        position: sticky !important;
        top: 5.5rem;
        align-self: flex-start !important;
        min-height: calc(100vh - 7rem);
        max-height: calc(100vh - 7rem);
        overflow-y: auto;
    }

    /* White card inside the grey panel, matching the reference's
       "Professional Preview" surface. */
    [data-testid="stColumn"]:has([data-gp-col="preview"]) [data-testid="stIFrame"] {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        box-shadow: var(--shadow-sm);
    }

    /* Item 1: the preview column's three empty states (render_preview_empty_
       state(), app.py) - a white waiting-card instead of st.info()'s blue
       alert box. Numbers from the reference's own empty-preview card
       (ResumeBuilder.tsx:548,564-566): `bg-white rounded-lg shadow-xl border
       border-gray-200`, empty content `flex flex-col items-center
       justify-center p-12 text-center opacity-40`, a 64px FileText icon in
       text-gray-300, `font-bold text-gray-400` copy. rounded-lg is 8px
       (var(--radius), same correction as the card-radius rule above);
       shadow-xl itself was judged too heavy for a page-level empty state -
       "soft shadow" per the task brief - so this uses var(--shadow-md)
       instead, the softer of this file's own two shadow tokens, rather than
       inventing a third. p-12 is 3rem. opacity-40 is approximated as 0.45 on
       the icon/text individually (var(--muted) already carries most of that
       fade, so a flat opacity on the whole card would also wash out the
       border/shadow, which the reference's own card keeps solid). */
    .gp-preview-empty {
        min-height: 60vh;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        gap: 1rem;
        padding: 3rem;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        box-shadow: var(--shadow-md);
    }

    .gp-preview-empty svg {
        color: var(--muted);
        opacity: 0.45;
    }

    .gp-preview-empty p {
        margin: 0;
        max-width: 26rem;
        color: var(--muted) !important;
        font-weight: 700;
        font-size: 0.95rem;
    }

    /* Item 1: the draggable splitter's own handle - see
       render_generator_splitter()'s docstring, further down, for the full
       rationale and its coupling to streamlit==1.61.1. Static appearance
       only, defined here (the main page's own stylesheet, not the
       components.html iframe's) because the handle element is inserted
       into *this* document, not the iframe - var(--brand)/var(--border)
       are already in scope via :root (css_root_block(), top of this
       block). The live drag width is set as inline styles by that
       function's injected script directly on the two stColumn elements,
       not through this class. */
    /* The handle is absolutely positioned so it consumes NO flex space.
       It used to be `flex: 0 0 auto` - an ordinary flex child - which broke
       the layout outright: Streamlit's stHorizontalBlock is `flex-wrap: wrap`
       with a 12px gap, and the two columns are sized to sum to exactly 100%,
       so adding an 8px child plus a second 12px gap overflowed the row and
       wrapped the preview column onto its own line *below* the workspace.
       Measured in a browser before the fix: row 969px wide vs 978px of
       children, preview column's top 1266px below the workspace column's -
       which is exactly the "預覽全部都在左邊" the owner reported.

       Out of flow, the handle can never overflow the row again. The row gets
       `position: relative` to anchor it, and `flex-wrap: nowrap` as a second
       guard so a future stray child cannot reintroduce the same wrap. */
    [data-testid="stHorizontalBlock"]:has(> .gp-split-handle) {
        position: relative;
        flex-wrap: nowrap !important;
    }

    .gp-split-handle {
        position: absolute;
        top: 0;
        bottom: 0;
        width: 8px;
        margin-left: -4px;
        border-radius: 999px;
        background: var(--border);
        cursor: col-resize;
        touch-action: none;
        z-index: 2;
        transition: background-color var(--ease);
    }

    .gp-split-handle:hover,
    .gp-split-handle.gp-split-active {
        background: var(--brand);
    }
</style>""").replace(
    # Plain string replace, not %-formatting: the stylesheet is full of literal
    # percentages (100%, 50%) that %-formatting would choke on.
    "__SIDEBAR_W__",
    # The *visible* rail width, not the section's clamped 200 - the strip has
    # to start where the sidebar visually ends.
    str(SIDEBAR_RAIL_PX if st.session_state.get("sidebar_collapsed") else SIDEBAR_EXPANDED_PX),
), unsafe_allow_html=True)

st.markdown(
    "<div id='small-screen-notice'>This app is built for a desktop browser. "
    "On a narrow screen the editor and PDF preview will not lay out correctly.</div>",
    unsafe_allow_html=True,
)

def render_sidebar_brand():
    """Logo chip + two-line wordmark + sub-label, as a single injected
    fragment, plus the hairline rule that separates it from the nav below.

    Deliberately one st.markdown() call, not three-plus stacked ones
    (st.markdown for the wordmark, st.caption for the sub-label, ...): the
    [data-testid="stVerticalBlock"] gap rule above applies between every
    direct child Streamlit puts in the sidebar, so stacked calls would read
    as loose, disconnected lines instead of one lockup anchoring the sidebar.
    A single fragment has only one such child, so there is nothing for that
    gap rule to apply between. Colour comes entirely from the .sb- classes
    in the stylesheet (var(--brand-dark), var(--surface), var(--muted), ...),
    themselves sourced from TOKENS via css_root_block() - nothing here is a
    literal hex value.
    """
    st.markdown(
        """<div class="sb-brand">
  <div class="sb-logo">AR</div>
  <div class="sb-wordmark">
    <div class="sb-wordmark-name">AI Resume<br>Studio</div>
    <div class="sb-micro-label">APPLICATION WORKSPACE</div>
  </div>
</div>
<hr class="sb-hairline">""",
        unsafe_allow_html=True,
    )

def render_sidebar_group_label(text):
    """One uppercase, letter-spaced micro-label - the "WORKSPACE" /
    "RECENT APPLICATIONS" style headers grouping the sidebar's sections."""
    st.markdown(f'<div class="sb-micro-label">{text}</div>', unsafe_allow_html=True)

def render_sidebar_recent_applications():
    """Up to three most-recent tracker rows, or nothing at all.

    This is the one section with a real cost trap: it needs Firestore data,
    but the sidebar renders on every rerun of every view. Two things keep
    that cheap:

    1. Logged-out sessions return before get_db() is even called, so there is
       never a Firestore round-trip (not even an init attempt) for a signed-
       out visitor.
    2. firebase_dashboard.fetch_applications() is itself the caching layer -
       it is keyed by st.session_state.app_records_email (so switching
       accounts can never serve the previous user's rows) and only re-hits
       Firestore when force_refresh_apps is set, which save_application()
       already flips to True on every successful write (see
       sync_application_to_tracker() in this file). Calling it again here on
       every sidebar render is therefore a session_state read, not a new
       Firestore call, on every rerun after the first. No second cache is
       layered on top of it here.

    If the fetch fails or simply returns nothing, this renders nothing at
    all - not even the group label - rather than an empty list or fabricated
    placeholder rows.
    """
    if not st.session_state.logged_in:
        return
    db = get_db()
    if db is None:
        return
    records = fetch_applications(db, st.session_state.user_email)
    rows = workspace.recent_applications(records)
    if not rows:
        return
    render_sidebar_group_label("RECENT APPLICATIONS")
    for i, row in enumerate(rows):
        label = f"{row['company']} — {row['role']}" if row["role"] else row["company"]
        if st.button(
            label,
            key=f"recent_app_{i}_{row['status_dot_token']}",
            icon=":material/fiber_manual_record:",
            use_container_width=True,
            help=label,
        ):
            st.session_state.active_view = workspace.TRACKER
            st.rerun()

def render_sidebar_account_block(email):
    """Avatar + email + "ACCOUNT · SETTINGS" micro-label, as one fragment -
    same reasoning as render_sidebar_brand() above: this is one visual unit,
    not three separately-spaced Streamlit elements. email is user-controlled
    (whatever they registered with) and lands in raw HTML, so it is escaped
    before interpolation; the truncation itself is CSS (text-overflow:
    ellipsis in .sb-account-email), not string slicing, so the full address
    is still available via the title tooltip."""
    initial = html.escape((email or "?")[:1].upper())
    safe_email = html.escape(email or "")
    st.markdown(
        f"""<div class="sb-account">
  <div class="sb-avatar">{initial}</div>
  <div class="sb-account-info">
    <div class="sb-account-email" title="{safe_email}">{safe_email}</div>
    <div class="sb-micro-label">ACCOUNT · SETTINGS</div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )

with st.sidebar:
    # One control, at the top, always visible in both states - the owner asked
    # for a single collapse button and nothing else. Icon-only so it reads the
    # same width whether the rail is open or shut.
    if st.button(
        "",
        key="sidebar_toggle",
        help="Expand sidebar" if st.session_state.sidebar_collapsed else "Collapse to icons",
        icon=":material/menu:" if st.session_state.sidebar_collapsed else ":material/menu_open:",
    ):
        st.session_state.sidebar_collapsed = not st.session_state.sidebar_collapsed
        # The width lives in the stylesheet, which is emitted near the top of
        # the script - so the new state only takes effect on a fresh run.
        st.rerun()

    # Always rendered - the owner wants the monogram to survive the collapse,
    # the way their reference rail keeps its "G" tile at the top. Only the
    # wordmark beside it is hidden, by the .sb-brand-text rule in the rail CSS.
    render_sidebar_brand()

    render_sidebar_group_label("WORKSPACE")
    for view, label, icon in workspace.VIEWS:
        if st.button(
            label,
            key=f"nav_{view}",
            use_container_width=True,
            type="primary" if st.session_state.active_view == view else "secondary",
            icon=icon,
        ):
            st.session_state.active_view = view
            # Rerun rather than falling through: the sidebar has already drawn
            # itself for the previous view, so without this the highlight and
            # the content below would disagree until the next interaction.
            st.rerun()

    render_sidebar_recent_applications()

    st.markdown("---")

    if st.session_state.logged_in:
        render_sidebar_account_block(st.session_state.user_email)
        if st.session_state.get("sync_error"):
            st.error(f"Cloud sync failed: {st.session_state.sync_error}")
        elif st.session_state.last_synced_at:
            st.caption(f"Saved to cloud at {st.session_state.last_synced_at}")
        else:
            st.caption("Changes save to the cloud automatically.")
        if st.button("Logout", use_container_width=True):
            clear_user_session()
            st.rerun()
    else:
        st.caption("Sign in to save your profile and track applications.")
        auth_mode = st.radio("Auth Mode", ["Login", "Register"], horizontal=True, label_visibility="collapsed")
        with st.form("auth_form"):
            e = st.text_input("Email")
            p = st.text_input("Password", type="password")
            if auth_mode == "Login":
                if st.form_submit_button("Login", type="primary", use_container_width=True):
                    email = e.strip()
                    auth_db = get_db()
                    if auth_db is not None:
                        ok, msg = authenticate_user(auth_db, email, p)
                        if ok:
                            # Start from a clean slate so nothing from a previous
                            # account on this browser session survives the switch.
                            clear_user_session()
                            st.session_state.logged_in = True; st.session_state.user_email = email
                            r, pr, k = load_user_profile(auth_db, email)
                            if r is not None:
                                st.session_state.resume_data = r
                            if pr is not None:
                                st.session_state.custom_prompt = pr
                            if k is not None:
                                st.session_state.api_key = k
                            st.session_state.base_editor_key += 1
                            # Session init ran before login, when resume_data was
                            # necessarily empty, so it always landed on Profile.
                            # Recompute now that the real profile has loaded.
                            st.session_state.active_view = workspace.initial_view(
                                resume_is_empty(st.session_state.resume_data)
                            )
                            # What we just loaded is by definition in sync, so
                            # autosave must not immediately write it back.
                            mark_profile_synced()
                            st.rerun()
                        else:
                            st.error(msg)
            else:
                if st.form_submit_button("Create Account", type="primary", use_container_width=True):
                    auth_db = get_db()
                    if auth_db is not None:
                        ok, msg = register_user(auth_db, e.strip(), p)
                        if ok: st.success(msg)
                        else: st.error(msg)
    with st.expander("Settings"):
        st.markdown("**API Settings**")
        if st.session_state.api_key:
            st.success("Gemini key connected")
            if st.button("Change key", use_container_width=True):
                st.session_state.api_key = ""
                st.rerun()
        else:
            st.caption("Add your Gemini key in the main panel to turn on the AI features.")

        st.checkbox(
            "Show advanced import tools",
            key="show_advanced_tools",
            help="Paste raw JSON in and out of the app. Not needed for normal use.",
        )

        # Deferred: session_state cannot be written for a key whose widget has
        # already been instantiated this run.
        if st.button("Reset All Data", use_container_width=True, type="secondary"):
            st.session_state.pending_reset = True
            st.rerun()

    st.caption("Developed by NSYSUHermit")

@st.fragment
def render_api_key_setup():
    """First-run gate. The key input used to live only in the sidebar, so a new
    user's first action was usually clicking an AI button that could not work."""
    with st.container(border=True):
        st.markdown("#### Step 1 — Connect your Gemini API key")
        st.markdown(
            "The AI features run on your own free Google key.\n\n"
            "1. Open [Google AI Studio](https://aistudio.google.com/app/apikey) and sign in\n"
            "2. Click **Create API key**, then copy it\n"
            "3. Paste it below"
        )
        key_input = st.text_input(
            "Gemini API key",
            type="password",
            key="api_key_input",
            placeholder="AIza...",
        )
        if st.button("Save and test key", type="primary"):
            ok, msg = run_ai_call(
                "Checking your key",
                lambda report: check_api_key(key_input, report),
                success=lambda r: r[0],
            )
            if ok:
                st.session_state.api_key = key_input.strip()
                st.session_state.pending_toast = "API key connected."
                st.rerun()
            else:
                st.error(msg)

if not st.session_state.api_key:
    render_api_key_setup()

active_view = st.session_state.active_view

# Rendered outside the workspaces so the outcome of a run stays visible wherever
# the user navigates next.
render_result_banner()

if active_view == workspace.PROFILE:      # 原 "Source"
    if resume_is_empty(st.session_state.resume_data):
        st.info(
            "**Start here.** Either upload an existing resume PDF below and let the AI fill "
            "the form in for you, or skip the upload and type straight into the fields."
        )
    with st.container(border=True):
        st.subheader("Quick Import")
        up = st.file_uploader("Upload PDF", type=["pdf"], key="up1", label_visibility="collapsed")
        no_key = not st.session_state.api_key
        if no_key:
            st.caption("Connect a Gemini API key above to enable PDF extraction.")
        if st.button("Extract Resume Data", type="primary", use_container_width=True, disabled=up is None or no_key):
            ok, msg, data = run_ai_call(
                "Extracting resume data",
                lambda report: parse_pdf_resume_to_json(up.getvalue(), st.session_state.api_key, report),
                success=lambda r: r[0],
            )
            if ok:
                st.session_state.resume_data = data
                st.session_state.base_editor_key += 1
                clear_generated_outputs()
                roles = len(data.get("experience") or [])
                schools = len(data.get("education") or [])
                set_result_banner(
                    title="Resume imported from your PDF",
                    details=[
                        f"{roles} roles" if roles else None,
                        f"{schools} schools" if schools else None,
                        "Check the fields below, then add a job description",
                    ],
                    actions=[("Add a job description", workspace.GENERATOR)],
                )
                st.rerun()
            else: st.error(msg)

    # Auto-save: Streamlit reruns on every widget change, so the editor's return
    # value already reflects the latest input. Writing it back unconditionally
    # means edits survive a workspace switch without a Save button.
    st.session_state.resume_data = render_resume_form_editor(
        st.session_state.resume_data,
        key_prefix=f"base_form_{st.session_state.base_editor_key}",
    )
    st.caption("Changes are saved automatically as you type.")

    if st.session_state.get("show_advanced_tools"):
        with st.expander("Advanced JSON Import"):
            raw_import = render_json_editor(
                json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False),
                key=f"base_json_import_{st.session_state.base_editor_key}",
                height=320,
            )
            if st.button("Apply JSON Import", use_container_width=True):
                try:
                    st.session_state.resume_data = json.loads(raw_import)
                    st.session_state.base_editor_key += 1
                    clear_generated_outputs()
                    st.toast("JSON imported.")
                    st.rerun()
                except json.JSONDecodeError as e:
                    st.error(f"Source JSON is invalid: {e}")

def render_quick_stats():
    """Quick-stat cards filling the whitespace above Source of Truth.

    Each card is only shown when a real number backs it - nothing here is a
    fabricated placeholder:
    - Experience Entries reads st.session_state.resume_data, which always
      exists (session init at the top of this file), so it is always shown -
      including a genuine 0 for an empty profile, which is an accurate count,
      not an invented one.
    - Latest ATS Score needs an actual scored optimize run
      (st.session_state.ats_metrics); omitted entirely when that is None
      rather than shown as a fake 0%.
    - Applications Recorded reads st.session_state.app_records, which
      firebase_dashboard.fetch_applications() populates only after a Tracker
      visit has already fetched it this session. Deliberately NOT fetched
      from here (no get_db()/fetch_applications() call in this function): a
      "quick" stats row at the top of Generator is not the place to trigger a
      new Firestore round-trip on every render, so this card simply reflects
      whatever is already in session_state, per the task's own framing
      ("numbers already available in session state"). Logged-out sessions
      never populate app_records, so the card is naturally absent, not a
      misleading 0 - satisfying the same rule without a special-cased check.
    """
    experience_count = len((st.session_state.resume_data or {}).get("experience") or [])
    cards = [("Experience Entries", str(experience_count), "Roles in your base Career Profile")]

    metrics = st.session_state.get("ats_metrics")
    if metrics and metrics.get("total"):
        cards.append((
            "Latest ATS Score",
            f"{metrics['optimized_pct']}%",
            "Keyword match rate from the most recent Optimize run",
        ))

    if st.session_state.get("logged_in") and "app_records" in st.session_state:
        cards.append((
            "Applications Recorded",
            str(len(st.session_state.app_records or [])),
            "Tracked in your application pipeline",
        ))

    for col, (label, value, help_text) in zip(st.columns(len(cards)), cards):
        col.metric(label, value, help=help_text)

def render_generator_workspace():
    """Generator 的左欄：頂部快速統計、資料來源、JD、策略、優化按鈕、可直接編輯的
    draft table，以及底部的匯出設定與 ATS 分析。"""
    # Zero-content marker for the two-tone column background (visual-polish
    # pass, item 6) - see the [data-testid="stColumn"]:has([data-gp-col="workspace"])
    # rule in the stylesheet block above for what actually paints the colour.
    #
    # This used to be a bare `st.container(key="gp_workspace_col")`, on the
    # stated assumption that an empty keyed container still renders a div
    # carrying `st-key-gp_workspace_col`. Checked in a real browser: it does
    # not. Streamlit emits no DOM node for a container with nothing in it, so
    # that class was absent from the document entirely and BOTH features that
    # depended on it - this background rule and the drag handle's anchoring -
    # silently did nothing. st.html() renders inline (not in an iframe) and
    # always produces a node, so the marker is real. The attribute is ours,
    # not Streamlit's, which also makes it immune to their class renames.
    st.html('<span data-gp-col="workspace" style="display:none"></span>')
    render_quick_stats()
    with st.container(border=True):
        st.subheader("Source of Truth")
        data = st.session_state.resume_data
        if resume_is_empty(data):
            st.caption("Your Career Profile is empty. Build it first — every rewrite starts from it.")
        else:
            st.caption(
                f"Career Profile  ·  {len(data.get('experience') or [])} roles"
                f"  ·  {len(data.get('education') or [])} schools"
            )
        if st.button("Edit Career Profile", use_container_width=True, icon=":material/arrow_forward:"):
            st.session_state.active_view = workspace.PROFILE
            st.rerun()

    st.subheader("Target & Strategy")
    # Both inputs mirror into durable keys. A widget key alone is dropped by
    # Streamlit on any rerun where the widget is not rendered, which is what
    # silently emptied the JD whenever the user switched workspace.
    jd = st.text_area(
        "Job description",
        value=st.session_state.jd_text,
        height=140,
        key=f"jd_input_{st.session_state.base_editor_key}",
        placeholder="Paste the job description here...",
    )
    with st.expander("Custom Strategy"):
        # Visual-polish pass, item 4: labelled "Custom Strategy" (was
        # "Strategy", collapsed) so the [data-testid="stWidgetLabel"]
        # micro-label rule above actually renders "CUSTOM STRATEGY" above
        # this field - the reference design's own second named example,
        # alongside "Job description" just above. The expander's own header
        # (same words, mixed case) is a different element - st.expander
        # gives its header no data-testid of its own to anchor on, and this
        # app has several other expanders whose titles are meant to stay
        # readable as normal clickable text (see the stWidgetLabel rule's
        # own comment) - so it is deliberately left as-is; this is the
        # field-level label the reference actually shows the micro-label
        # treatment on.
        strategy = st.text_area(
            "Custom Strategy",
            value=st.session_state.custom_prompt,
            height=200,
            key=f"cp_input_{st.session_state.base_editor_key}",
        )
    st.session_state.jd_text = jd
    st.session_state.custom_prompt = strategy

    if not st.session_state.api_key:
        st.caption("Connect a Gemini API key above to enable optimization.")
    c1, c2 = st.columns(2)
    with c1:
        # Item 4 (visual-polish follow-up), owner: 「optimizing resume 的動畫就
        # 跑在同一顆按鈕上就好不要額外延展」. st.empty() gives the button its own
        # placeholder slot so run_ai_call(..., target=optimize_slot) can
        # overwrite that exact slot with the in-flight spinner+milestone line
        # (ui_feedback.run_ai_call()'s own docstring has the full rationale)
        # instead of opening a panel below it - the button's row becomes the
        # status row, nothing new is added to the layout. Confirmed in
        # streamlit==1.61.1 via a standalone AppTest script before writing
        # this: a placeholder holding a clicked button can be overwritten
        # with st.markdown() in the same run with no exception, and the
        # button is cleanly gone from the tree afterward.
        optimize_slot = st.empty()
        optimize_clicked = optimize_slot.button(
            "Optimize Resume",
            type="primary",
            use_container_width=True,
            disabled=not st.session_state.api_key,
            key="optimize_resume_btn",
        )
        if optimize_clicked:
            if jd:
                clear_generated_outputs()
                ok, rep = run_ai_call(
                    "Optimizing resume",
                    lambda report: ai_optimize_and_update(jd, strategy, report),
                    success=lambda r: r[0],
                    target=optimize_slot,
                )
                if ok:
                    # The banner was filled in by ai_optimize_and_update with
                    # the real numbers; no toast needed.
                    st.rerun()
                else:
                    # No rerun on failure (see run_ai_call()'s docstring), so
                    # optimize_slot is left showing the frozen failure
                    # message - redraw the real button into it here so the
                    # row is clickable again immediately, instead of dead
                    # until some unrelated interaction happens to rerun the
                    # page. A second explicit key: Streamlit raises on two
                    # elements sharing one key in the same run, even through
                    # the same placeholder (confirmed the same way, via
                    # AppTest, before relying on it).
                    optimize_slot.button(
                        "Optimize Resume",
                        type="primary",
                        use_container_width=True,
                        disabled=not st.session_state.api_key,
                        key="optimize_resume_btn_retry",
                    )
                    st.error(rep)
            else:
                st.warning("Paste a job description before optimizing.")
    with c2:
        p_text = ai.build_rewrite_prompt(jd if jd else "JD", st.session_state.resume_data, strategy)
        b64 = base64.b64encode(p_text.encode('utf-8')).decode('utf-8')
        components.html(f"""
            <body style="margin:0; padding:0;">
                <button id="copyPromptBtn" onclick="copyPrompt()" style="
                    width:100%; height:42px; border-radius:8px;
                    background:{TOKENS['surface']}; color:{TOKENS['text']}; border:1px solid {TOKENS['border']};
                    cursor:pointer; font-weight:650; font-family:{FONT_STACK};
                    display:flex; align-items:center; justify-content:center;
                    box-shadow:0 1px 2px rgba(15,23,42,0.06);
                    transition:background-color 180ms ease-in-out,border-color 180ms ease-in-out,box-shadow 180ms ease-in-out,color 180ms ease-in-out;">
                    Copy Prompt
                </button>
            </body>
            <script>
            function copyPrompt() {{
                try {{
                    const b64 = "{b64}";
                    const text = decodeURIComponent(escape(window.atob(b64)));
                    const textArea = document.createElement("textarea");
                    textArea.value = text;
                    textArea.style.position = "fixed"; textArea.style.left = "-9999px"; textArea.style.top = "0";
                    document.body.appendChild(textArea);
                    textArea.focus(); textArea.select();
                    const successful = document.execCommand('copy');
                    document.body.removeChild(textArea);
                    if (successful) {{
                        const btn = document.getElementById('copyPromptBtn');
                        btn.innerText = 'Copied';
                        btn.style.borderColor = '{TOKENS['success']}'; btn.style.color = '{TOKENS['success']}';
                        setTimeout(() => {{
                            btn.innerText = 'Copy Prompt';
                            btn.style.borderColor = '{TOKENS['border']}'; btn.style.color = '{TOKENS['text']}';
                        }}, 2000);
                    }}
                }} catch (err) {{ console.error(err); }}
            }}
            </script>
            """, height=44)

    if st.session_state.optimized_resume_data:
        if optimized_result_is_stale():
            st.warning("Source JSON has changed since the current optimized result was created. Re-run Optimize Resume before generating a new PDF.")
        # Item 2: the draft table used to render inline here, which made the
        # left column enormous (every experience/education/projects/skills
        # grid stacked at once, above Edit Optimized JSON, above Export
        # Settings, above ATS analysis). It now lives behind a dialog, opened
        # by this button, beside the existing Edit Optimized JSON button that
        # opens the other dialog. Both dialogs stay outside the fragment:
        # editing the resume has to propagate to the whole script, not just
        # this box.
        dcol1, dcol2 = st.columns(2)
        with dcol1:
            if st.button("Draft Table", use_container_width=True, key="open_draft_table_dialog"):
                render_optimized_draft_table()
        with dcol2:
            if st.button("Edit Optimized JSON", use_container_width=True): edit_opt_dialog()

    # 手動匯入外部推論結果
    if st.session_state.get("show_advanced_tools"):
        with st.expander("Manual Result Import"):
            st.caption("If you ran the rewrite elsewhere, paste its JSON here. Include a top-level \"keywords\" list to score coverage as well.")
            manual_json = st.text_area("Paste the externally inferred JSON here:", height=200, key="manual_ats_json")
            if st.button("Apply Manual Result", use_container_width=True):
                try:
                    res = json.loads(manual_json)
                    if "optimized_resume" not in res:
                        st.error("JSON structure missing 'optimized_resume'.")
                    else:
                        clear_pdf_outputs_and_tracking()
                        optimized = res.get("optimized_resume")
                        st.session_state.ats_analysis = res
                        st.session_state.optimized_resume_data = optimized
                        st.session_state.changelog = res.get("changelog", "")
                        st.session_state.suggested_metrics = res.get("suggested_metrics", []) or []
                        st.session_state.optimized_source_snapshot = resume_snapshot(st.session_state.resume_data)
                        keywords = res.get("keywords") or (res.get("screening") or {}).get("keywords") or []
                        st.session_state.ats_metrics = ai.keyword_report(
                            keywords, st.session_state.resume_data, optimized
                        ) if keywords else None
                        # Wholesale replacement: the draft table's widgets are keyed
                        # off opt_editor_key so they reseed from the freshly imported
                        # data instead of writing back whatever they last held.
                        st.session_state.opt_editor_key += 1
                        st.session_state.pending_toast = "Manual result applied."
                        st.rerun()
                except Exception as e:
                    st.error(f"Invalid JSON: {e}")

    # 允許手動匯入已優化的 JSON (方便使用者直接複製格式)
    if st.session_state.get("show_advanced_tools"):
        with st.expander("Manual Data Import"):
            st.caption("If you already have a structured resume JSON, paste it here to skip AI optimization.")
            manual_opt_json = st.text_area("Paste Optimized JSON here:", height=200, key="manual_opt_input")
            if st.button("Apply Manual Data", use_container_width=True):
                try:
                    manual_data = json.loads(manual_opt_json)
                    st.session_state.optimized_resume_data = manual_data
                    st.session_state.ats_analysis = None
                    st.session_state.ats_metrics = None
                    st.session_state.changelog = ""
                    st.session_state.optimized_source_snapshot = None
                    clear_pdf_outputs_and_tracking()
                    # Same reason as Manual Result Import above: force the draft
                    # table to reseed from this import instead of the previous data.
                    st.session_state.opt_editor_key += 1
                    st.toast("Manual data applied.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Invalid JSON: {e}")

    # 右欄現在只剩 PDF 本身 (render_preview)，匯出設定與 ATS 分析改放在左欄底部。
    render_export_settings()

    if st.session_state.optimized_resume_data:
        render_ats_analysis()
    else:
        st.caption("Optimize a resume to see how it scores against the job description.")

@st.dialog("Draft table", width="large")
def render_optimized_draft_table():
    """The optimized result as a directly-editable table. Called only once
    st.session_state.optimized_resume_data exists (guarded by the caller,
    render_generator_workspace()).

    Auto-saves into st.session_state.optimized_resume_data on every rerun -
    st.data_editor's return value already reflects the latest edit on the
    very rerun it happens, so there is no separate Save button, the same
    pattern render_resume_form_editor() already uses for the base profile in
    Profile view.

    Field scope follows the task literally: target company/role/summary as
    labelled inputs above the table (three unrelated scalars read worse as a
    one-row grid than as normal fields), and experience/education/projects/
    skills as st.data_editor grids - the resume's genuinely tabular parts.
    Heading, cover letter, the "about me" notes and patents are NOT part of
    this table; they stay reachable only through Edit Optimized JSON below
    (edit_opt_dialog(), unchanged, still not gated behind
    show_advanced_tools - see tests/test_tracker_guard.py's
    test_advanced_optimized_json_import_resets_tracked_application_id, which
    depends on that button always being visible). This table is an
    additional, friendlier surface, not a replacement for the dialog. Any key
    this table does not manage (patents, heading, ...) passes through
    unchanged via **current below, so a manually-imported JSON's fields are
    never silently dropped just because this table has no column for them.

    Change detection compares the widgets' output (`updated`) against a
    `baseline` built by running the *unedited* seed data through the exact
    same seed -> data_editor -> compact-rows pipeline, rather than against
    `current` (the raw pre-conversion dict) directly. The pipeline is not a
    lossless round trip on its own - skills_to_rows()/rows_to_skills() in
    particular normalises a missing or empty "skills" dict into a non-empty
    default ({"set1": {"title": "Skills", "items": []}}) even with zero user
    edits. Comparing against raw `current` would treat that normalisation
    alone as an "edit" on the very first render after every optimize/import,
    wiping resume_preview_bytes/resume_dl_data (clear_pdf_outputs() below)
    before the user ever downloaded anything from the new result - confirmed
    against tests/test_tracker_guard.py's download-button tests, several of
    which set a sparse optimized_resume_data (e.g. only "target_company")
    alongside pre-set resume_dl_data and assert the download button is still
    there. Comparing two values produced by the *same* pipeline cancels that
    normalisation noise out and leaves only genuine widget-level edits.
    """
    current = st.session_state.optimized_resume_data or {}
    # Manual Data Import, Manual Result Import and Advanced Optimized JSON
    # Import all accept arbitrary pasted JSON with no shape validation, so
    # optimized_resume_data can be a list, string, number, etc. instead of an
    # object - current.get(...) a few lines down would crash the whole
    # Generator view over it. Coerce to {} so the table below just renders
    # itself empty instead (compact_rows() above is the matching per-row
    # guard for the fields that are objects but whose own contents are not).
    if not isinstance(current, dict):
        current = {}
    ekey = st.session_state.opt_editor_key

    with st.container(border=True):
        st.markdown("**Optimized Draft**")
        st.caption(
            "Edit any cell in place - changes save automatically and feed the next "
            "Generate PDF. For every other field (heading, cover letter, patents, "
            "...), use Edit Optimized JSON below."
        )

        c1, c2 = st.columns(2)
        with c1:
            target_company = st.text_input(
                "Target Company", value=current.get("target_company", ""), key=f"draft_company_{ekey}"
            )
        with c2:
            target_role = st.text_input(
                "Target Role", value=current.get("target_role", ""), key=f"draft_role_{ekey}"
            )
        summary = st.text_area(
            "Summary", value=current.get("summary", ""), height=100, key=f"draft_summary_{ekey}"
        )

        st.caption("Experience")
        exp_seed = experience_seed_rows(current.get("experience"))
        experience_rows = st.data_editor(
            exp_seed,
            key=f"draft_experience_{ekey}",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "company": st.column_config.TextColumn("Company"),
                "role": st.column_config.TextColumn("Role"),
                "time_duration": st.column_config.TextColumn("Duration"),
                "company_location": st.column_config.TextColumn("Location"),
                "details": st.column_config.TextColumn("Bullets (one per line)", width="large"),
            },
        )

        st.caption("Education")
        education_seed = editable_seed(current.get("education", []), EDUCATION_ROW_FIELDS)
        education_rows = st.data_editor(
            education_seed,
            key=f"draft_education_{ekey}",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "school": st.column_config.TextColumn("School"),
                "time_period": st.column_config.TextColumn("Time Period"),
                "degree": st.column_config.TextColumn("Degree"),
                "school_location": st.column_config.TextColumn("Location"),
            },
        )

        st.caption("Projects")
        projects_seed = editable_seed(current.get("projects", []), PROJECT_ROW_FIELDS)
        project_rows = st.data_editor(
            projects_seed,
            key=f"draft_projects_{ekey}",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "name": st.column_config.TextColumn("Name"),
                "time": st.column_config.TextColumn("Time"),
                "description": st.column_config.TextColumn("Description", width="large"),
            },
        )

        st.caption("Skills")
        skills_seed = skills_to_rows(current.get("skills", {}))
        skill_rows = st.data_editor(
            skills_seed,
            key=f"draft_skills_{ekey}",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "key": st.column_config.TextColumn("Set Key"),
                "title": st.column_config.TextColumn("Category"),
                "items": st.column_config.TextColumn("Items (comma separated)", width="large"),
            },
        )

    updated = {
        **current,
        "target_company": target_company,
        "target_role": target_role,
        "summary": summary,
        "experience": rows_to_experience(experience_rows),
        "education": compact_rows(education_rows, EDUCATION_ROW_FIELDS),
        "projects": compact_rows(project_rows, PROJECT_ROW_FIELDS),
        "skills": rows_to_skills(skill_rows),
    }
    baseline = {
        **current,
        "target_company": current.get("target_company", ""),
        "target_role": current.get("target_role", ""),
        "summary": current.get("summary", ""),
        "experience": rows_to_experience(exp_seed),
        "education": compact_rows(education_seed, EDUCATION_ROW_FIELDS),
        "projects": compact_rows(projects_seed, PROJECT_ROW_FIELDS),
        "skills": rows_to_skills(skills_seed),
    }
    if resume_snapshot(updated) != resume_snapshot(baseline):
        st.session_state.optimized_resume_data = updated
        # Same call as edit_opt_dialog()'s Save Changes handler -
        # clear_pdf_outputs(), NOT clear_pdf_outputs_and_tracking(): editing
        # the current result in place is still the same application, not a
        # new one, so tracked_application_id must not reset here (see
        # clear_pdf_outputs_and_tracking()'s own docstring for the dedupe
        # guard this protects). optimized_source_snapshot is also untouched -
        # it snapshots resume_data (the base profile) at optimize time, not
        # optimized_resume_data, so optimized_result_is_stale() (which only
        # compares those two) is unaffected by draft-table edits either way.
        clear_pdf_outputs()

@st.dialog("Edit Optimized Data", width="large")
def edit_opt_dialog():
    edit = render_resume_form_editor(
        st.session_state.optimized_resume_data,
        key_prefix=f"opt_form_{st.session_state.opt_editor_key}",
    )
    if st.button("Save Changes", use_container_width=True):
        st.session_state.optimized_resume_data = edit
        st.session_state.opt_editor_key += 1
        clear_pdf_outputs()
        st.rerun()

    with st.expander("Advanced Optimized JSON Import"):
        raw_opt_import = render_json_editor(
            json.dumps(st.session_state.optimized_resume_data, indent=4, ensure_ascii=False),
            key=f"opt_json_import_{st.session_state.opt_editor_key}",
            height=320,
        )
        if st.button("Apply Optimized JSON Import", use_container_width=True):
            try:
                st.session_state.optimized_resume_data = json.loads(raw_opt_import)
                st.session_state.opt_editor_key += 1
                clear_pdf_outputs_and_tracking()
                st.rerun()
            except json.JSONDecodeError as e:
                st.error(f"Optimized JSON is invalid: {e}")

def render_ats_analysis():
    """ATS 分析區塊的內容（左欄底部）；呼叫端已確認有優化結果。"""
    if st.session_state.changelog:
        st.markdown("### Optimization Changelog")
        st.info(st.session_state.changelog)

    # Requirements the rewrite deliberately did not claim. This is the
    # counterpart to banning invented metrics: instead of a fabricated
    # number, the user gets a list of what to supply themselves.
    if st.session_state.suggested_metrics:
        st.markdown("### Add These Yourself")
        st.caption("The rewrite left these out because your resume had no evidence for them. Nothing here was invented on your behalf.")
        for item in st.session_state.suggested_metrics:
            st.markdown(f"- {item}")

    m = st.session_state.ats_metrics
    if m and m.get("total"):
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric(
            "Match Rate",
            f"{m['optimized_pct']}%",
            delta=f"{m['optimized_pct'] - m['original_pct']:+d} pts vs original",
        )
        mc2.metric("Keywords Hit", f"{m['optimized_count']}/{m['total']}")
        mc3.metric("Newly Covered", len(m['newly_added']))
        st.progress(min(100, m['optimized_pct']) / 100)
        k1, k2 = st.columns(2)
        with k1:
            st.success("Matched Keywords")
            for k in m.get('optimized_hits', []):
                st.markdown(f"- `{k}`" + (" (new)" if k in m.get('newly_added', []) else ""))
        with k2:
            st.error("Missing Keywords")
            st.caption("Still absent. Add them only where they are genuinely true of you.")
            for k in m.get('missing_keywords', []):
                st.markdown(f"- `{k}`")
    elif m is None:
        st.info("No keyword list was available for this result, so coverage was not scored.")

# Shared between render_export_settings() (left column) and render_preview()'s
# cached base-resume preview (right column) - two different @st.fragments that
# both need the same durable list of section names.
BLOCK_ORDER_OPTIONS = ["Summary", "Experience", "Education", "Projects & Patents", "Skills"]

@st.fragment
def render_export_settings():
    """Template and section order.

    Kept in its own fragment, separate from the preview: fiddling with the
    template or the section order is the most common interaction here, and it
    previously reran all ~1200 lines and re-encoded the whole PDF into the
    preview iframe every time. Now lives at the bottom of the left column; the
    preview it feeds (render_preview) is a sibling fragment in the right
    column - see the app-scope st.rerun() below for why that still works
    across the column boundary.
    """
    with st.container(border=True):
        st.subheader("Export Settings")
        st.caption("Select your preferred template and section order, then generate the final PDFs.")
        tmpl = st.selectbox("Template", ["Tech", "Business"], key="tm")
        # Keyed (previously wasn't) so render_preview() - a different fragment,
        # in the right column - can read the current order to build the cache
        # key for the base-resume preview.
        order = st.multiselect("Order", BLOCK_ORDER_OPTIONS, default=BLOCK_ORDER_OPTIONS, key="export_order")
        if st.button(
            "Generate PDF",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.optimized_resume_data is None,
        ):
            if optimized_result_is_stale():
                st.error("This optimized result is stale. Re-run Optimize Resume so the PDF uses the latest Source JSON.")
            else:
                with st.spinner("Generating..."):
                    d = st.session_state.optimized_resume_data
                    co = safe_filename_part(d.get('target_company'), 'Company')
                    ro = safe_filename_part(d.get('target_role'), 'Role')
                    clear_pdf_outputs()
                    rb = generate_preview_pdf_bytes(d, template_file_for(tmpl), order)
                    if rb:
                        st.session_state.resume_preview_bytes = rb
                        # 統一檔名格式 (由使用者要求)
                        st.session_state.resume_dl_data = {"bytes": rb, "name": f"{co}_{ro}_Resume.pdf"}
                    cb = generate_cover_letter_pdf_bytes(d)
                    if cb:
                        st.session_state.cover_letter_preview_bytes = cb
                        # 確保與履歷檔名格式一致
                        st.session_state.cl_dl_data = {"bytes": cb, "name": f"{co}_{ro}_CL.pdf"}
                if rb or cb:
                    st.session_state.pending_toast = "PDF generated."
                    # App-scope rerun so the sibling preview fragment picks up
                    # the new bytes; a fragment-scope rerun would not reach it.
                    st.rerun()
                else:
                    st.error("No PDF was generated.")

def render_preview_empty_state(message):
    """White waiting-card for the preview column's three empty states.

    Owner's spec, verbatim: 「左邊就是全白 右邊預覽就是全灰底中間留著白色預覽空間等待
    pdf進來顯示」 (left entirely white, right entirely grey, with a white card in
    the middle waiting for the PDF to arrive). These three call sites used to
    be st.info(), which renders Streamlit's blue alert box - a warning, not a
    waiting state. Matches the reference's own empty-preview card
    (ResumeBuilder.tsx:548,564-566 - the desktop "Professional Preview" panel):
    a tall bordered white surface holding a centred muted document glyph above
    centred muted copy (`h-full flex flex-col items-center justify-center p-12
    text-center opacity-40`, a 64px FileText icon in text-gray-300, `font-bold
    text-gray-400` copy) - not an alert. Message wording is exactly whatever
    the caller used to pass to st.info(); only the presentation changed.
    Rendered via st.html() rather than components.html(): st.html() inserts
    into the main document, not an iframe, so the .gp-preview-empty class
    (app.py's stylesheet block) and its var(--...) colours are visible to it -
    an iframe could not see those custom properties at all (see theme.py's
    own module docstring on exactly this iframe limitation).
    """
    st.html(
        '<div class="gp-preview-empty">'
        '<svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 2v6h6"/>'
        '</svg>'
        f'<p>{html.escape(message)}</p>'
        '</div>'
    )

@st.fragment
def render_preview():
    """Generator 的右欄：只剩 PDF 本身，加左上角切換與右上角下載，不再有分頁。

    優化結果的真實預覽 (resume_preview_bytes / cover_letter_preview_bytes) 一律
    優先；在那之前，Resume 這一側改顯示 base 履歷的快取預覽 (base_preview_pdf)，
    讓使用者一進 Generator 右欄就有東西可看，而不是空白一片。Cover Letter 在
    真正 Generate PDF 之前沒有對應的 base 版本可顯示——這點只有 Resume 有，
    設計文件裡也只針對 base 履歷本身要求快取。
    """
    # Zero-content marker for the two-tone column background (visual-polish
    # pass, item 6) - see render_generator_workspace()'s matching marker,
    # and the [data-testid="stColumn"]:has(...) rules in the stylesheet
    # block, for the full explanation. Re-emitted on every fragment-scoped
    # rerun of this function same as any other element in it; harmless -
    # it is an idempotent, display:none marker, not state. See the workspace
    # marker's comment for why this is st.html() and not an empty container.
    st.html('<span data-gp-col="preview" style="display:none"></span>')
    # A selectbox, not a segmented control. The two-option segmented control
    # needed 156px of intrinsic width and this row gives its left cell only
    # 2/5 of the preview panel - measured 95px once the splitter narrowed the
    # panel to 239px - so the two options wrapped onto separate lines and
    # stopped reading as one switch. CSS could not fix that: the wrap happens
    # in the column above the widget, not inside it. A dropdown has no minimum
    # width to satisfy, so it degrades cleanly at any panel width.
    top_left, top_right = st.columns([2, 3])
    with top_left:
        ch = st.selectbox(
            "Target",
            ["Resume", "Cover Letter"],
            index=0,
            label_visibility="collapsed",
            key="tr",
        )

    target = st.session_state.resume_preview_bytes if ch == "Resume" else st.session_state.cover_letter_preview_bytes
    dl = st.session_state.resume_dl_data if ch == "Resume" else st.session_state.cl_dl_data

    with top_right:
        if dl:
            downloaded = st.download_button(
                "", dl["bytes"], dl["name"],
                icon=":material/download:", help=f"Download {dl['name']}",
            )
            if st.session_state.logged_in:
                if st.session_state.get("tracked_application_id") is not None:
                    st.caption("Already recorded in the tracker. Downloading again will not add another row.")
                else:
                    st.caption("Downloading records this application in the tracker.")
            # Checked inline rather than via on_click: this fragment's callback
            # phase is a different execution context than its normal body, and
            # sync_application_to_tracker() needs to force an app-scope rerun
            # (see its own comment) the same proven way render_export_settings
            # does — from ordinary fragment-body code, not from a callback.
            if downloaded:
                sync_application_to_tracker()

    if target:
        render_pdf_js(target)
    elif ch == "Resume":
        data = st.session_state.resume_data
        if resume_is_empty(data):
            # 未優化前的預覽必須快取，不能急切編譯 - 履歷是空的就不編譯，
            # 直接指向 Career Profile，不要拿一份空白 PDF 浪費 lualatex。
            render_preview_empty_state("Your Career Profile is empty. Build it first — every rewrite starts from it.")
        else:
            # `or` here would default an intentionally-cleared multiselect
            # (export_order == []) back to the full list. render_export_settings
            # always runs first (left column, above this in render order), so
            # the key is only ever really absent before that first render.
            saved_order = st.session_state.get("export_order")
            order = tuple(saved_order if saved_order is not None else BLOCK_ORDER_OPTIONS)
            template_label = st.session_state.get("tm") or "Tech"
            try:
                base_bytes = base_preview_pdf(resume_snapshot(data), template_file_for(template_label), order)
            except PreviewCompileFailed:
                # Same message a returned None used to produce - only the
                # caching behaviour behind it changed (see base_preview_pdf()'s
                # docstring, Minor 9).
                base_bytes = None
            if base_bytes:
                render_pdf_js(base_bytes)
            else:
                render_preview_empty_state("Preview unavailable. Check the LaTeX log above.")
    else:
        render_preview_empty_state("Optimize your resume and generate a PDF to preview the cover letter.")

def render_progress_strip():
    """Thin full-width status strip pinned to the very top of the Generator
    view - replaces the old floating pill (position:fixed, centred,
    pill-radius'd, ~4.3rem tall) that the owner said took too much vertical
    space to read as "thin".

    Draws the same four (label, done) stages the pill did -
    workspace.application_progress() still owns that logic (unit-tested in
    tests/test_workspace.py) and its labels are untouched here; this
    function only renders it, it does not re-decide what counts as "done".
    The fill bar's width and the highlighted stop both track the
    *highest-index completed stage*, not a running count of how many are
    done - the two can differ if stages ever complete out of order (see
    tests/test_floating_progress.py's non-monotonic test) - same rule the
    pill used.

    No walking figure here: see the #gp-status-strip comment in the
    stylesheet block (further up) for why it was dropped rather than
    shrunk into this much thinner container. theme.walker_svg() itself is
    unchanged and still used by ui_feedback.run_ai_call()'s compact status
    panel - this function no longer calls it.
    """
    stages = workspace.application_progress(
        jd_text=st.session_state.jd_text,
        has_optimized=st.session_state.optimized_resume_data is not None,
        has_pdf=st.session_state.resume_preview_bytes is not None,
        is_tracked=st.session_state.get("tracked_application_id") is not None,
    )
    total = len(stages)
    done_indices = [i for i, (_, done) in enumerate(stages) if done]
    completed = len(done_indices)
    # Highest-index completed stage, not a running count: see the docstring.
    current_index = max(done_indices) if done_indices else 0

    def stop_pct(index):
        # Evenly spaced stops across whatever the track's actual width ends
        # up being - a percentage needs no pixel constant shared with the
        # stylesheet's .gp-strip-track width.
        return round(index * 100 / (total - 1), 3) if total > 1 else 0.0

    stops_html = "".join(
        f'<span class="gp-strip-stop{" gp-strip-stop-done" if done else ""}" '
        f'style="left:{stop_pct(i)}%" title="{label}"></span>'
        for i, (label, done) in enumerate(stages)
    )

    if completed == 0:
        status_text = "Not started"
    elif completed == total:
        status_text = f"All steps complete · {completed}/{total}"
    else:
        status_text = f"{stages[current_index][0]} · {completed}/{total}"

    fill_pct = stop_pct(current_index)

    st.markdown(
        f"""<div id="gp-status-strip" role="group" aria-label="Application progress: {status_text}">
  <div class="gp-strip-track">
    <div class="gp-strip-fill" style="width:{fill_pct}%"></div>
    {stops_html}
  </div>
  <span class="gp-strip-label">{status_text}</span>
</div>""",
        unsafe_allow_html=True,
    )

def remove_generator_splitter():
    """Strip a leftover drag handle from the parent document.

    Counterpart to render_generator_splitter(). The handle lives in
    window.parent.document, not in the component iframe, so it survives the
    iframe being removed when the user leaves Generator - the bar stayed
    painted across Profile and Tracker until this ran.

    Also clears the inline flex-basis the splitter wrote onto the two columns,
    so a later view's columns are not left carrying Generator's ratio.
    """
    components.html(
        """<script>
        (function () {
          try {
            var doc = window.parent.document;
            var handles = doc.querySelectorAll(".gp-split-handle");
            for (var i = 0; i < handles.length; i++) {
              if (handles[i].parentElement) handles[i].parentElement.removeChild(handles[i]);
            }
            var cols = doc.querySelectorAll('[data-testid="stColumn"]');
            for (var j = 0; j < cols.length; j++) {
              cols[j].style.removeProperty("flex");
              cols[j].style.removeProperty("max-width");
            }
          } catch (e) {
            /* Same posture as the injector: never let a DOM surprise break
               the host page. */
          }
        })();
        </script>""",
        height=0,
    )


def render_generator_splitter():
    """Draggable resize handle between the Generator's two columns.

    RATIONALE - why this exists and why it is built this way: the owner
    explicitly rejected the `Panel width` segmented_control (three fixed
    presets - PANEL_RATIOS, removed along with this) that used to stand in
    for this, twice, and asked for a real drag handle. Streamlit's Python
    API has no drag primitive, and st.columns()'s ratios are fixed at the
    moment st.columns(...) runs on the server - there is no server-side way
    to make that interactive. A real bidirectional custom component
    (streamlit-component-lib, a full separate React build with its own
    postMessage bridge) is the "correct" way to build a resizable layout in
    Streamlit, but is out of proportion for a single-file app.

    The technique used instead: st.components.v1.html() renders into a real
    <iframe>. Streamlit's own IFrameUtil gives that iframe a `sandbox`
    attribute that includes BOTH `allow-scripts` and `allow-same-origin`
    together (confirmed by reading the shipped streamlit==1.61.1 frontend
    bundle, IFrameUtil.*.js) - that specific combination is the one
    documented to re-grant a sandboxed frame its embedder's origin, so a
    script running inside it can reach `window.parent.document` and mutate
    the real app DOM directly, same-origin, no message-passing bridge
    needed. That is the "same-origin iframe" this task's brief describes -
    confirmed against the actual shipped bundle here, not assumed.

    COUPLING TO streamlit==1.61.1 - a second, independent reason (beyond
    requirements.txt's own Python-3.14-wheel reasoning) the version pin has
    to stay exact:
      - `allow-same-origin` in the iframe sandbox is Streamlit's own
        implementation choice, not a guarantee. A future release tightening
        that sandbox (a real possibility - loosening cross-frame access is
        a genuine security trade-off) would make every DOM lookup below
        throw, caught by this script's own guards, so the handle would just
        silently stop appearing rather than break the page - but it would
        be gone.
      - Every lookup is anchored on data-testid attributes
        (stMainBlockContainer, stHorizontalBlock, stColumn) that Streamlit
        does not treat as public API and has renamed across versions before.
      - findSplit() (below) identifies the two Generator columns via the
        `st-key-gp_workspace_col` / `st-key-gp_preview_col` marker classes
        the two zero-content st.container(key=...) calls in
        render_generator_workspace()/render_preview() produce - documented,
        stable Streamlit behaviour ("key ... will be used as a CSS class
        name prefixed with st-key-", elements/layouts.py), not a private
        heuristic, but it still assumes each marker's nearest
        [data-testid="stColumn"] ancestor is that column and that both
        columns share one immediate-parent stHorizontalBlock. A future
        release changing how a keyed container's class is attached, or
        restructuring how nested st.columns() calls appear in the tree,
        could defeat it.
      - The width-forcing technique (setting flex/maxWidth inline styles
        directly on the two stColumn elements) assumes columns are laid out
        with CSS flexbox today, as they are in streamlit==1.61.1.
    Any of these silently disables the handle (the guards mean it fails
    closed, never with an exception the user sees) rather than restoring
    the old fixed-ratio behaviour - which is exactly why upgrading this
    dependency is not just a version bump; this script needs re-verifying
    against whatever DOM the new version actually ships.

    SURVIVING RERUNS: every Streamlit rerun re-executes app.py top to
    bottom, which re-renders (and, per React's own reconciliation, can
    replace) the Generator's column DOM nodes - including any node this
    script inserted into them that Streamlit's own virtual DOM does not
    know about. The injected script handles this by being idempotent and
    self-healing rather than run-once: ensure() (below) (a) re-finds the
    row and its two columns from scratch every time it runs, (b)
    re-applies the persisted ratio to them unconditionally (cheap - setting
    a style property to its current value is a no-op paint), and (c) only
    creates a new handle element if one is not already present as a direct
    child of the row. A MutationObserver on window.parent.document.body
    calls ensure() again on every subsequent childList mutation anywhere in
    the app - including the mutation ensure() itself just caused by
    inserting the handle, which is safe: the very next check on that same
    call already finds the handle in place and stops. So if a later
    rerun's reconciliation ever removes the handle or resets a column's
    inline width, the next mutation batch re-attaches/re-applies it without
    needing a fresh page load. This iframe/script instance (and its
    MutationObserver) dies the moment the user navigates off Generator,
    since render_generator_splitter() is only ever called from the
    Generator branch below - Profile's and Tracker's element trees never
    contain this <iframe> at all, so nothing has to detect the view change
    and tear itself down explicitly.

    UNVERIFIED - be precise about this: this repo's test harness (AppTest)
    sees the emitted HTML string, never a rendered DOM or a real pointer
    event, so nothing here can be proven to actually drag from this
    codebase. What tests/test_generator_splitter.py does verify is that the
    script is emitted only on the Generator view (never Profile/Tracker)
    and that its JS parses. That the handle finds the right columns, drags
    smoothly, clamps to [25, 75], persists across a real reload, and
    survives a real rerun in a real browser needs a human with a browser -
    that has not been done here.
    """
    components.html(
        """
<script>
(function () {
  "use strict";

  var MIN_PCT = 25;
  var MAX_PCT = 75;
  var STORAGE_KEY = "gp-splitter-left-pct";

  function clamp(n, lo, hi) {
    return Math.max(lo, Math.min(hi, n));
  }

  function loadRatio() {
    try {
      var raw = window.parent.localStorage.getItem(STORAGE_KEY);
      var n = parseFloat(raw);
      return isNaN(n) ? 50 : clamp(n, MIN_PCT, MAX_PCT);
    } catch (e) {
      return 50;
    }
  }

  function saveRatio(pct) {
    try {
      window.parent.localStorage.setItem(STORAGE_KEY, String(pct));
    } catch (e) {
      /* localStorage unavailable (private mode, quota, ...) - the drag
         still worked for this session, only persistence is lost. */
    }
  }

  function findSplit(doc) {
    // Anchored on the two zero-content marker containers app.py itself
    // renders as the first element inside each Generator column
    // (st.container(key="gp_workspace_col") / st.container(key="gp_preview_col"),
    // in render_generator_workspace()/render_preview()) rather than on "the
    // first stHorizontalBlock with exactly two stColumn children, in
    // document order, that is not itself nested inside a column" - an
    // earlier version of this function used exactly that heuristic, and it
    // has a real collision: render_result_banner() (app.py, called
    // unconditionally, above the per-view dispatch) renders its own
    // st.columns([20, 1]) text/dismiss-button row whenever a banner is set -
    // an ordinary state, e.g. immediately after every successful Optimize
    // Resume - and that row is ALSO a top-level two-column stHorizontalBlock
    // with no stColumn ancestor, appearing earlier in the DOM than the real
    // Generator split. A document-order scan would silently grab that row
    // instead and hang the handle off the banner, not the workspace/preview
    // split. Locating by marker sidesteps the ambiguity entirely, present or
    // future: `key=` on any Streamlit element is documented to add a
    // `st-key-<key>` CSS class (streamlit==1.61.1 elements/layouts.py,
    // LayoutsMixin.container()'s own docstring: "it will be used as a CSS
    // class name prefixed with st-key-") - a public, stable mechanism, not a
    // st-emotion-cache-* build hash - and the same one the stylesheet block
    // above already relies on for item 6's two-tone column backgrounds
    // ([data-testid="stColumn"]:has(.st-key-gp_workspace_col), just above
    // this handle's own .gp-split-handle rules), so both features share one
    // definition of "which column is which" instead of two that could
    // silently disagree.
    var main = doc.querySelector('[data-testid="stMainBlockContainer"]');
    if (!main) return null;
    var leftMark = main.querySelector('[data-gp-col="workspace"]');
    var rightMark = main.querySelector('[data-gp-col="preview"]');
    if (!leftMark || !rightMark) return null; // Not on Generator, or not rendered yet.
    var left = leftMark.closest('[data-testid="stColumn"]');
    var right = rightMark.closest('[data-testid="stColumn"]');
    if (!left || !right || left === right) return null;
    var row = left.parentElement;
    if (!row || !row.getAttribute || row.getAttribute("data-testid") !== "stHorizontalBlock") return null;
    if (right.parentElement !== row) return null;
    return { row: row, left: left, right: right };
  }

  // GAP_PX must match stHorizontalBlock's own `gap`. With the handle out of
  // flow the row has exactly two flex children and therefore one gap, so the
  // columns have to sum to (100% - GAP_PX) or the row overflows and wraps -
  // which is the bug this whole arrangement exists to avoid. Splitting the
  // gap evenly keeps the handle centred on the true boundary.
  var GAP_PX = 12;

  function applyRatio(left, right, pct, handle) {
    var rightPct = 100 - pct;
    var half = GAP_PX / 2;
    left.style.flex = "0 0 calc(" + pct + "% - " + half + "px)";
    left.style.maxWidth = "calc(" + pct + "% - " + half + "px)";
    right.style.flex = "0 0 calc(" + rightPct + "% - " + half + "px)";
    right.style.maxWidth = "calc(" + rightPct + "% - " + half + "px)";
    if (handle) handle.style.left = pct + "%";
  }

  function findHandle(row) {
    for (var i = 0; i < row.children.length; i++) {
      var child = row.children[i];
      if (child.classList && child.classList.contains("gp-split-handle")) {
        return child;
      }
    }
    return null;
  }

  function makeHandle(doc, row, left, right) {
    var handle = doc.createElement("div");
    handle.className = "gp-split-handle";
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", "vertical");
    handle.setAttribute("aria-label", "Resize workspace and preview panels");

    var dragging = false;
    var startX = 0;
    var startPct = 50;
    var rowWidth = 1;

    function pctFromEvent(e) {
      var dx = e.clientX - startX;
      return clamp(startPct + (dx / rowWidth) * 100, MIN_PCT, MAX_PCT);
    }

    function onMove(e) {
      if (!dragging) return;
      applyRatio(left, right, pctFromEvent(e), handle);
    }

    function onUp(e) {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("gp-split-active");
      saveRatio(pctFromEvent(e));
      try {
        handle.releasePointerCapture(e.pointerId);
      } catch (err) {
        /* capture already released/lost - nothing to clean up */
      }
    }

    // pointerdown/pointermove/pointercapture, not mousedown/mousemove: with
    // the pointer captured to the handle, events keep firing even once the
    // cursor leaves its (deliberately slim) hit area mid-drag.
    handle.addEventListener("pointerdown", function (e) {
      dragging = true;
      startX = e.clientX;
      rowWidth = row.getBoundingClientRect().width || 1;
      startPct = clamp(parseFloat(left.style.maxWidth) || 50, MIN_PCT, MAX_PCT);
      handle.classList.add("gp-split-active");
      try {
        handle.setPointerCapture(e.pointerId);
      } catch (err) {
        /* pointer capture unavailable - drag still works as long as the
           cursor stays over the handle, it just will not survive leaving
           it. Better than throwing. */
      }
      e.preventDefault();
    });
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);

    return handle;
  }

  function ensure() {
    try {
      var doc = window.parent.document;
      var found = findSplit(doc);
      if (!found) return; // Not on Generator, or the DOM is not ready yet.
      // Handle first, ratio second: applyRatio() also positions the handle, so
      // it needs one to exist. Creating it is the only non-idempotent step -
      // everything after re-applies cleanly on every MutationObserver tick.
      var handle = findHandle(found.row);
      if (!handle) {
        handle = makeHandle(doc, found.row, found.left, found.right);
        found.row.insertBefore(handle, found.right);
      }
      applyRatio(found.left, found.right, loadRatio(), handle);
    } catch (e) {
      /* A DOM shape this script did not anticipate, or same-origin access
         unexpectedly denied - never let that break the host page. */
    }
  }

  try {
    ensure();
    var target = window.parent.document.body;
    if (target) {
      // Re-runs ensure() on every subsequent DOM mutation anywhere in the
      // app, so a later Streamlit rerun that tears down and rebuilds the
      // Generator's columns (removing this script's own handle along with
      // them, and resetting whatever inline width it had set) gets
      // self-healed on the very next mutation batch - see this function's
      // own "SURVIVING RERUNS" docstring section for the full reasoning.
      new MutationObserver(function () {
        ensure();
      }).observe(target, { childList: true, subtree: true });
    }
  } catch (e) {
    /* window.parent inaccessible for some reason - fail silent, no handle. */
  }
})();
</script>
""",
        height=0,
    )

if active_view == workspace.GENERATOR:
    render_progress_strip()
    # Sits with the progress strip: once it reads 4/4 there has to be a way to
    # start the next application without hunting for Reset All Data, which
    # wipes the Career Profile too.
    _new_app_col, _ = st.columns([1, 4])
    with _new_app_col:
        if st.button("New application", use_container_width=True,
                     icon=":material/add:", key="new_application"):
            start_new_application()
            st.session_state.pending_toast = "Started a new application."
            st.rerun()
    left, right = st.columns(2)
    with left:
        render_generator_workspace()
    with right:
        # 右欄現在只有 render_preview() 自己：切換、下載、PDF 本身，沒有分頁。
        # 進度已移至頂端狀態條；輸出設定與 ATS 已移進左欄底部。
        render_preview()
    # Draggable resize handle between the two columns above - see its own
    # docstring for the full rationale, its coupling to streamlit==1.61.1,
    # and exactly what is/is not verified about it. Called after both
    # columns have rendered: purely for readability (render the split, then
    # wire up how to resize it) - the injected script itself runs
    # client-side, after the whole page has painted, so it would work
    # regardless of where in this Python script it was called from.
    render_generator_splitter()
else:
    # The handle is inserted into window.parent.document, so it outlives the
    # component iframe that created it: navigating away from Generator tore
    # down the iframe but left the bar sitting across Profile and Tracker.
    # Nothing inside that iframe can clean up after itself once it is gone,
    # so removal has to be driven from the view that is actually rendering.
    remove_generator_splitter()

if active_view == workspace.TRACKER:      # 原 "Tracker"
    if st.session_state.logged_in:
        tracker_db = get_db()
        if tracker_db is not None:
            render_interview_progress(tracker_db, st.session_state.user_email)
            render_dashboard(tracker_db, st.session_state.user_email)
        else:
            st.warning("Tracker is unavailable until Firebase secrets are configured.")
    else: st.warning("Login first.")

# Runs last, once every view has rendered, so the profile written to Firestore
# reflects the edits made during this run rather than the previous one.
autosave_profile()
