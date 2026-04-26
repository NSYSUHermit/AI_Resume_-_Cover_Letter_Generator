import streamlit as st
import json
from utils.pdf_generator import generate_resume_pdf, generate_cover_letter_pdf
from components.ui_elements import get_glass_overlay_html

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
        template = st.selectbox("Select LaTeX Template:", ["main.tex", "elsa_main.tex"])
        block_order = st.multiselect(
            "Block Order:", 
            ["Summary", "Experience", "Education", "Projects & Patents", "Skills"],
            default=["Summary", "Experience", "Education", "Projects & Patents", "Skills"]
        )
        
        if st.button("🔨 Generate Resume PDF", type="primary", use_container_width=True):
            overlay = st.empty()
            overlay.markdown(get_glass_overlay_html("Compiling LaTeX...", st.session_state.get('animal_emoji', '🐕'), "#8a2be2"), unsafe_allow_html=True)
            
            pdf_bytes, err = generate_resume_pdf(data, template, block_order)
            overlay.empty()
            
            if pdf_bytes:
                st.session_state.resume_preview_bytes = pdf_bytes
                st.success("PDF Compiled Successfully!")
            else:
                st.error(f"LaTeX Error: {err}")

    with col_pre:
        st.subheader("Preview")
        if st.session_state.get("resume_preview_bytes"):
            st.download_button("📥 Download Resume PDF", st.session_state.resume_preview_bytes, file_name="resume.pdf", mime="application/pdf")
            # PDF 預覽元件 (簡化版)
            st.info("Download the PDF to view the final result.")
