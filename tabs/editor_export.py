import streamlit as st
import json
import base64
from utils.pdf_generator import generate_resume_pdf, generate_cover_letter_pdf
from components.ui_elements import get_glass_overlay_html
import streamlit.components.v1 as components
from utils.pdf_generator import generate_resume_pdf # 確保引用正確的 generator

def render_pdf_js(pdf_bytes, height=650):
    """補回原本強大的 PDF.js 預覽功能"""
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_js_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
        <style>
            body {{ margin: 0; padding: 0; background-color: transparent; display: flex; flex-direction: column; align-items: center; }}
            canvas {{ margin-bottom: 10px; box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.15); width: 100%; border-radius: 4px; }}
        </style>
    </head>
    <body>
        <div id="pdf-container" style="width: 100%;"></div>
        <script>
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
            var binaryString = window.atob('{base64_pdf}');
            var binaryLen = binaryString.length;
            var bytes = new Uint8Array(binaryLen);
            for (var i = 0; i < binaryLen; i++) {{ bytes[i] = binaryString.charCodeAt(i); }}
            var loadingTask = pdfjsLib.getDocument({{data: bytes}});
            loadingTask.promise.then(function(pdf) {{
                var container = document.getElementById('pdf-container');
                for (var pageNum = 1; pageNum <= pdf.numPages; pageNum++) {{
                    pdf.getPage(pageNum).then(function(page) {{
                        var scale = 1.5;
                        var viewport = page.getViewport({{scale: scale}});
                        var canvas = document.createElement('canvas');
                        var context = canvas.getContext('2d');
                        canvas.height = viewport.height;
                        canvas.width = viewport.width;
                        container.appendChild(canvas);
                        var renderContext = {{ canvasContext: context, viewport: viewport }};
                        page.render(renderContext);
                    }});
                }}
            }});
        </script>
    </body>
    </html>
    """
    components.html(pdf_js_html, height=height, scrolling=True)

def render_tab():
    st.header("🛠️ Editor & Export")
    
    source_choice = st.radio("Select Data Source:", ["Base Profile", "Optimized Profile"], horizontal=True)
    data = st.session_state.resume_data if source_choice == "Base Profile" else st.session_state.optimized_resume_data
    
    if not data:
        st.warning("No data found for the selected source.")
        return

    col_cfg, col_pre = st.columns([1, 1])
    
    with col_cfg:
        st.subheader("Template Settings")
        # --- 換回你原本喜歡的標籤名稱 ---
        template_map = {
            "Engineer Style (Standard)": "main.tex",
            "Consultant Style (Modern)": "elsa_main.tex"
        }
        template_label = st.selectbox("Select Resume Style:", list(template_map.keys()))
        selected_template = template_map[template_label]
        
        block_order = st.multiselect(
            "Block Order:", 
            ["Summary", "Experience", "Education", "Projects & Patents", "Skills"],
            default=["Summary", "Experience", "Education", "Projects & Patents", "Skills"]
        )
        
        if st.button("🔨 Generate Resume PDF", type="primary", use_container_width=True):
            overlay = st.empty()
            overlay.markdown(get_glass_overlay_html("Compiling your professional resume...", st.session_state.get('animal_emoji', '🐕'), "#8a2be2"), unsafe_allow_html=True)
            
            pdf_bytes, err = generate_resume_pdf(data, selected_template, block_order)
            overlay.empty()
            
            if pdf_bytes:
                st.session_state.resume_preview_bytes = pdf_bytes
                st.success(f"Successfully generated {template_label}!")
            else:
                st.error(f"LaTeX Error: {err}")
        
        if st.session_state.get("resume_preview_bytes"):
            st.download_button("📥 Download PDF", st.session_state.resume_preview_bytes, file_name="resume.pdf", mime="application/pdf", use_container_width=True)

    with col_pre:
        st.subheader("Live Preview")
        if st.session_state.get("resume_preview_bytes"):
            render_pdf_js(st.session_state.resume_preview_bytes)
        else:
            st.info("Click 'Generate' to see the preview here.")
