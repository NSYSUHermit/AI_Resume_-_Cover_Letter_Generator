import streamlit as st
import jinja2
from datetime import datetime
import subprocess
import os
import json
import tempfile
import shutil
import base64
import streamlit.components.v1 as components
from firebase_dashboard import init_firebase, authenticate_user, register_user, render_dashboard, save_application, render_interview_progress, save_user_profile, load_user_profile
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
            editable_seed(data.get("education", []), ["school", "time_period", "degree", "school_location"]),
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

    exp_seed = []
    for exp in data.get("experience", []) or []:
        if isinstance(exp, dict):
            exp_seed.append({
                "company": exp.get("company", ""),
                "role": exp.get("role", ""),
                "time_duration": exp.get("time_duration", ""),
                "company_location": exp.get("company_location", ""),
                "details": details_to_text(exp.get("details", [])),
            })
    exp_seed = editable_seed(exp_seed, ["company", "role", "time_duration", "company_location", "details"])
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
            editable_seed(data.get("projects", []), ["name", "time", "description"]),
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

    experience = []
    for row in compact_rows(experience_rows, ["company", "role", "time_duration", "company_location", "details"]):
        experience.append({
            "company": row["company"],
            "role": row["role"],
            "time_duration": row["time_duration"],
            "company_location": row["company_location"],
            "details": text_to_details(row["details"]),
        })

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
        "education": compact_rows(education_rows, ["school", "time_period", "degree", "school_location"]),
        "experience": experience,
        "projects": compact_rows(project_rows, ["name", "time", "description"]),
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
    # render_generator_panel()，在 fragment 之外，不會跟著 fragment-scoped
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
def render_pdf_js(pdf_bytes, max_pages=None, height=800):
    """Render a PDF inline with pdf.js.

    Re-embedding the document as base64 is the most expensive thing this app
    does on a rerun, so callers cap `max_pages` unless the user asks for the
    full document. Canvases are appended synchronously in page order; the
    previous version appended them from the getPage callback, so pages could
    land out of order whenever one resolved before an earlier one.
    """
    if not pdf_bytes: return
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    cap = "null" if max_pages is None else str(int(max_pages))
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
  var cap={cap};
  var last=(cap===null)?pdf.numPages:Math.min(pdf.numPages,cap);
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
  if(last<pdf.numPages){{
    document.getElementById('note').textContent='Showing '+last+' of '+pdf.numPages+' pages. Tick "Render all pages" to see the rest.';
  }}
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

# Lightweight visual system: native CSS only, no UI/animation framework.
st.markdown("<style>\n" + css_root_block() + """

    html, body, [data-testid="stAppViewContainer"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: var(--bg);
        color: var(--text);
    }

    /* Renamed from .main .block-container; the old selector matched nothing
       after the 1.6x DOM change, so the width cap was silently not applied. */
    [data-testid="stMainBlockContainer"] {
        padding-top: 3.25rem;
        padding-bottom: 3rem;
        max-width: 1320px;
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

    h1, h2, h3, h4 {
        color: var(--text);
        letter-spacing: 0;
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
    input,
    textarea {
        transition: background-color var(--ease), border-color var(--ease), box-shadow var(--ease), color var(--ease), transform var(--ease) !important;
    }

    .stButton button,
    .stDownloadButton button {
        border-radius: var(--radius) !important;
        min-height: 42px !important;
        font-weight: 650 !important;
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
    .stDownloadButton button:hover {
        border-color: var(--border-strong) !important;
        box-shadow: var(--shadow-md);
        transform: translateY(-1px);
    }

    .stButton button[kind="primary"] {
        background: var(--brand) !important;
        border-color: var(--brand) !important;
        color: #ffffff !important;
    }

    .stButton button[kind="primary"]:hover {
        background: var(--brand-dark) !important;
        border-color: var(--brand-dark) !important;
    }

    /* Streamlit dropped BaseWeb entirely, so every data-baseweb hook is gone. */
    .stButton button:focus-visible,
    .stDownloadButton button:focus-visible,
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

    hr {
        border-color: var(--border);
        margin: 1.1rem 0;
    }

    [data-testid="stAlert"] {
        border-radius: var(--radius);
        border: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
    }

    [data-testid="stMetric"] {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 0.85rem 1rem;
        box-shadow: var(--shadow-sm);
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
</style>""", unsafe_allow_html=True)

st.markdown(
    "<div id='small-screen-notice'>This app is built for a desktop browser. "
    "On a narrow screen the editor and PDF preview will not lay out correctly.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### AI Resume Studio")
    st.caption("Resume, cover letter, and application tracking.")

    st.caption("WORKSPACE")
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
    st.markdown("---")

    if st.session_state.logged_in:
        st.success(f"**User:** `{st.session_state.user_email}`")
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

def render_generator_workspace():
    """Generator 的左欄：資料來源、JD、策略、優化按鈕。"""
    with st.container(border=True):
        st.markdown("**Source of Truth**")
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

    st.markdown("**Target & Strategy**")
    # Both inputs mirror into durable keys. A widget key alone is dropped by
    # Streamlit on any rerun where the widget is not rendered, which is what
    # silently emptied the JD whenever the user switched workspace.
    jd = st.text_area(
        "Job description",
        value=st.session_state.jd_text,
        height=260,
        key=f"jd_input_{st.session_state.base_editor_key}",
        placeholder="Paste the job description here...",
    )
    with st.expander("Custom Strategy"):
        strategy = st.text_area(
            "Strategy",
            value=st.session_state.custom_prompt,
            height=200,
            key=f"cp_input_{st.session_state.base_editor_key}",
            label_visibility="collapsed",
        )
    st.session_state.jd_text = jd
    st.session_state.custom_prompt = strategy

    if not st.session_state.api_key:
        st.caption("Connect a Gemini API key above to enable optimization.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Optimize Resume", type="primary", use_container_width=True, disabled=not st.session_state.api_key):
            if jd:
                clear_generated_outputs()
                ok, rep = run_ai_call(
                    "Optimizing resume",
                    lambda report: ai_optimize_and_update(jd, strategy, report),
                    success=lambda r: r[0],
                )
                if ok:
                    # The banner was filled in by ai_optimize_and_update with
                    # the real numbers; no toast needed.
                    st.rerun()
                else: st.error(rep)
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
        # The dialog stays outside the fragment: editing the resume has to
        # propagate to the whole script, not just this box.
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
                        clear_pdf_outputs()
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
                    clear_pdf_outputs()
                    st.toast("Manual data applied.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Invalid JSON: {e}")

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
                clear_pdf_outputs()
                st.rerun()
            except json.JSONDecodeError as e:
                st.error(f"Optimized JSON is invalid: {e}")

def render_ats_analysis():
    """ATS 分頁的內容；呼叫端已確認有優化結果。"""
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

@st.fragment
def render_export_settings():
    """Template and section order.

    Kept in its own fragment, separate from the preview: fiddling with the
    template or the section order is the most common interaction here, and it
    previously reran all ~1200 lines and re-encoded the whole PDF into the
    preview iframe every time.
    """
    with st.container(border=True):
        st.subheader("Export Settings")
        st.caption("Select your preferred template and section order, then generate the final PDFs.")
        tmpl = st.selectbox("Template", ["Tech", "Business"], key="tm")
        order = st.multiselect("Order", ["Summary", "Experience", "Education", "Projects & Patents", "Skills"], default=["Summary", "Experience", "Education", "Projects & Patents", "Skills"])
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
                    rb = generate_preview_pdf_bytes(d, "main.tex" if "Tech" in tmpl else "elsa_main.tex", order)
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

@st.fragment
def render_preview():
    st.subheader("Preview")
    if st.session_state.resume_preview_bytes or st.session_state.cover_letter_preview_bytes:
        ch = st.radio("Target", ["Resume", "Cover Letter"], horizontal=True, label_visibility="collapsed", key="tr")
        target = st.session_state.resume_preview_bytes if ch == "Resume" else st.session_state.cover_letter_preview_bytes
        dl = st.session_state.resume_dl_data if ch == "Resume" else st.session_state.cl_dl_data
        if dl:
            downloaded = st.download_button(
                f"Download {dl['name']}",
                dl["bytes"],
                dl["name"],
                use_container_width=True,
            )
            if st.session_state.logged_in:
                st.caption("Downloading records this application in the tracker.")
            # Checked inline rather than via on_click: this fragment's callback
            # phase is a different execution context than its normal body, and
            # sync_application_to_tracker() needs to force an app-scope rerun
            # (see its own comment) the same proven way render_export_settings
            # does — from ordinary fragment-body code, not from a callback.
            if downloaded:
                sync_application_to_tracker()
        # Checking the layout only needs page one; rasterising every page on
        # each rerun was pure waste.
        all_pages = st.checkbox("Render all pages", value=False, key="pdf_all_pages")
        if target: render_pdf_js(target, max_pages=None if all_pages else 1)
        else: st.info(f"The {ch} data is missing.")
    else: st.info("Click 'Generate PDF' to see preview.")

def render_generator_panel():
    """Generator 的右欄：進度、輸出設定、預覽與 ATS。"""
    st.caption("THIS APPLICATION")
    for label, done in workspace.application_progress(
        jd_text=st.session_state.jd_text,
        has_optimized=st.session_state.optimized_resume_data is not None,
        has_pdf=st.session_state.resume_preview_bytes is not None,
        is_tracked=st.session_state.get("tracked_application_id") is not None,
    ):
        icon = "check_circle" if done else "radio_button_unchecked"
        colour = TOKENS["success"] if done else TOKENS["muted"]
        st.markdown(
            f":material/{icon}: <span style='color:{colour}'>{label}</span>",
            unsafe_allow_html=True,
        )
    st.markdown("---")

    render_export_settings()

    preview_tab, ats_tab = st.tabs(["Preview", "ATS"])
    with preview_tab:
        render_preview()
    with ats_tab:
        st.caption("Keyword coverage is counted here in Python by matching the JD's keyword list against your resume text, so every number below can be checked by hand.")
        if st.session_state.optimized_resume_data:
            render_ats_analysis()
        else:
            st.caption("Optimize a resume to see how it scores against the job description.")

if active_view == workspace.GENERATOR:
    left, right = st.columns([6, 4])
    with left:
        render_generator_workspace()
    with right:
        render_generator_panel()

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
