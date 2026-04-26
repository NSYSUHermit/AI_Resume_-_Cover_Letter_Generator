import os
import json
import tempfile
import shutil
import subprocess
import io
from docx import Document
from docx.shared import Pt, Inches
from datetime import datetime
from utils.tex_utils import clean_json_for_tex

def compile_latex(temp_dir, template_name, timeout=30):
    """通用的 LaTeX 編譯邏輯"""
    try:
        process = subprocess.run(
            ['lualatex', '-interaction=nonstopmode', '-halt-on-error', template_name],
            cwd=temp_dir,
            capture_output=True,
            timeout=timeout
        )
        pdf_path = os.path.join(temp_dir, template_name.replace('.tex', '.pdf'))
        if process.returncode == 0 and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                return f.read(), None
        else:
            return None, process.stdout.decode('utf-8', errors='ignore')
    except subprocess.TimeoutExpired:
        return None, "⚠️ LaTeX compilation timed out."
    except Exception as e:
        return None, str(e)

def generate_resume_pdf(data, template_name="main.tex", block_order=None):
    """生成履歷 PDF"""
    # 先對資料進行 LaTeX 轉義處理
    clean_data = clean_json_for_tex(data)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        shutil.copy(template_name, temp_dir)
        tex_path = os.path.join(temp_dir, template_name)
        
        # 讀取模板並處理動態區塊 (BLOCKS_PLACEHOLDER)
        with open(tex_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        if block_order and "BLOCKS_PLACEHOLDER" in template_content:
            blocks_latex = ""
            for block in block_order:
                if block == "Summary":
                    blocks_latex += "\\directlua{printSummary()}\n"
                elif block == "Experience":
                    section_title = "PROFESSIONAL EXPERIENCE" if "elsa" in template_name else "WORK EXPERIENCE"
                    blocks_latex += f"\\section{{{section_title}}}\n"
                    if "elsa" in template_name: blocks_latex += "  \\vspace{4pt}\n"
                    blocks_latex += "  \\directlua{printExperience()}\n"
                elif block == "Education":
                    blocks_latex += f"\\section{{EDUCATION}}\n  \\directlua{printEducation()}\n"
                elif block == "Projects & Patents":
                    blocks_latex += "\\directlua{printProjectsAndPatents()}\n"
                elif block == "Skills":
                    section_title = "CORE SKILLS" if "elsa" in template_name else "SKILLS"
                    blocks_latex += f"\\section{{{section_title}}}\n  \\directlua{printSkills()}\n"
            
            template_content = template_content.replace("BLOCKS_PLACEHOLDER", blocks_latex)
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(template_content)

        # 寫入 JSON 供 Lua 讀取
        temp_json_path = os.path.join(temp_dir, "ml_resume.json")
        with open(temp_json_path, "w", encoding="utf-8") as f:
            json.dump(clean_data, f, ensure_ascii=False, indent=4)
            
        return compile_latex(temp_dir, template_name)

def generate_cover_letter_pdf(resume_data):
    """生成求職信 PDF"""
    clean_data = clean_json_for_tex(resume_data)
    heading = clean_data.get('heading', {})
    cl_content = clean_data.get('cover_letter', '')
    
    header_tex = "\\begin{flushright}\n"
    if heading.get('name'): header_tex += f"{{\\Large\\bfseries {heading['name']}}} \\\\[1em]\n"
    for field in ['email', 'phone', 'linkedin', 'website']:
        if heading.get(field): header_tex += f"{heading[field]} \\\\\n"
    header_tex += "\\end{flushright}\n\\vspace{1em}\n\\today\n\\vspace{2em}\n\n"

    latex_template = r"""
\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{fontspec}
\usepackage{parskip}
\begin{document}
""" + header_tex + cl_content.replace("\n", "\n\n") + r"""
\end{document}
"""
    with tempfile.TemporaryDirectory() as temp_dir:
        tex_filename = "cover_letter.tex"
        with open(os.path.join(temp_dir, tex_filename), "w", encoding="utf-8") as f:
            f.write(latex_template)
        return compile_latex(temp_dir, tex_filename)
