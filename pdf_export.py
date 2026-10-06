"""LaTeX → PDF export and the inline pdf.js viewer.

Lives outside app.py for the same reason docx_export.py does: app.py is a
top-level Streamlit script, so anything defined there can only be reached by
running the whole UI. The Generator (app.py) and the Tracker
(firebase_dashboard.py) both need to compile a resume JSON to PDF, and
firebase_dashboard.py cannot import app.py (app.py imports it), so the shared
code sits here where both can import it directly.

`subprocess.run` is deliberately called through the module (never imported
by name): tests/test_profile_export.py and tests/test_tracker_preview.py fake
lualatex by patching `subprocess.run`.
"""
import streamlit as st
import streamlit.components.v1 as components
import jinja2
import subprocess
import os
import json
import tempfile
import shutil
import base64
from theme import FONT_STACK

# Shared between render_export_settings() (left column) and render_preview()'s
# cached base-resume preview (right column) - two different @st.fragments that
# both need the same durable list of section names.
BLOCK_ORDER_OPTIONS = ["Summary", "Experience", "Education", "Projects & Patents", "Skills"]

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

# Shown when lualatex is missing from PATH entirely. That is a different
# failure from a LaTeX compile error and needs a different answer: no amount of
# editing the resume will fix it, so the log excerpt the compile-error branch
# prints would be pure noise. Reachable on Streamlit Cloud whenever
# packages.txt is absent - see packages.txt.disabled for why it currently is.
LATEX_MISSING_MESSAGE = (
    "PDF generation is unavailable in this deployment: LuaLaTeX is not installed. "
    "Use the Word (.docx) download instead — it is built from the same data and "
    "needs no LaTeX. Everything else (AI optimization, ATS analysis, the tracker) "
    "works normally."
)

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
    except FileNotFoundError:
        st.error(LATEX_MISSING_MESSAGE)
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
    except FileNotFoundError:
        st.error(LATEX_MISSING_MESSAGE)
        return None
    except Exception as e:
        st.error(f"Cover Letter generation error: {e}")
        return None

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
