import streamlit as st
import json
import difflib
import streamlit.components.v1 as components

@st.dialog("🔍 AI Optimization Diff (Base vs Optimized)", width="large")
def show_diff_dialog(base_json, opt_json):
    """補回原本漂亮的 Diff 對照功能"""
    base_lines = json.dumps(base_json, indent=4, ensure_ascii=False).splitlines()
    opt_lines = json.dumps(opt_json, indent=4, ensure_ascii=False).splitlines()
    
    html_diff = difflib.HtmlDiff().make_file(
        base_lines, opt_lines, 
        fromdesc="Base Profile (Original)", todesc="Optimized Profile (AI Generated)",
        context=True, numlines=5
    )
    
    # 注入 Dark Mode CSS
    custom_css = """
    <style>
        body { font-family: 'Courier New', Courier, monospace; font-size: 13px; background-color: #0e1117; color: #fafafa; margin: 0; padding: 10px;}
        table.diff { width: 100%; border-collapse: collapse; }
        table.diff th { background-color: #262730; border: 1px solid #444; padding: 4px; text-align: left; }
        table.diff td { padding: 4px; border: 1px solid #333; word-wrap: break-word; max-width: 300px; }
        .diff_header { background-color: #262730; color: #888; text-align: center; width: 1%; }
        .diff_add { background-color: rgba(46, 160, 67, 0.4); }
        .diff_chg { background-color: rgba(227, 179, 65, 0.4); }
        .diff_sub { background-color: rgba(255, 75, 75, 0.4); }
        .diff_next { display: none; }
    </style>
    """
    html_diff = html_diff.replace("</head>", custom_css + "</head>")
    components.html(html_diff, height=650, scrolling=True)

def render_tab():
    st.header("📊 ATS Analysis Report")
    
    if not st.session_state.get("optimized_resume_data"):
        st.info("Please run the AI Optimizer first to see the analysis report.")
        return

    col_main, col_side = st.columns([7, 3])
    
    with col_main:
        # --- ATS Metrics ---
        metrics = st.session_state.get("ats_metrics")
        if metrics:
            st.subheader("ATS Keyword Match Rate")
            c1, c2, c3 = st.columns(3)
            c1.metric("Keywords Found", metrics.get("optimized_count", 0), delta=f"+{len(metrics.get('newly_added', []))}")
            c2.metric("Total JD Keywords", metrics.get("total", 0))
            c3.metric("Match Score", f"{metrics.get('optimized_pct', 0)}%", delta=f"{metrics.get('optimized_pct', 0) - metrics.get('original_pct', 0)}%")
            
            st.progress(metrics.get("optimized_pct", 0) / 100)
            
            with st.expander("📝 Detailed Keyword Analysis"):
                st.write("**✅ Newly Added Keywords:**")
                st.write(", ".join(metrics.get("newly_added", [])) if metrics.get("newly_added") else "None")
                st.write("**❌ Still Missing Keywords:**")
                st.write(", ".join(metrics.get("missing_keywords", [])) if metrics.get("missing_keywords") else "None")
        
        st.markdown("---")
        st.subheader("🤖 AI Changelog")
        st.info(st.session_state.get("changelog", "No changelog provided."))
        
        if st.button("🔍 View Detailed Changes (Diff)", use_container_width=True):
            show_diff_dialog(st.session_state.resume_data, st.session_state.optimized_resume_data)

    with col_side:
        with st.container(border=True):
            st.subheader("📥 External JSON")
            st.caption("Import JSON from ChatGPT/Claude")
            ext_json = st.text_area("Paste JSON here", height=300)
            if st.button("Apply External JSON", use_container_width=True):
                try:
                    st.session_state.optimized_resume_data = json.loads(ext_json)
                    st.success("External JSON applied!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Invalid JSON: {e}")
