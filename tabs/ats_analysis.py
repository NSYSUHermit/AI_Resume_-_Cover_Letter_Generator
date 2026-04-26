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
    st.header("📊 ATS Analysis & External Import")
    
    col_main, col_side = st.columns([7, 3])
    
    with col_main:
        if st.session_state.get("optimized_resume_data"):
            # --- ATS Metrics ---
            metrics = st.session_state.get("ats_metrics")
            if metrics:
                st.subheader("ATS Keyword Match Rate")
                c1, c2, c3 = st.columns(3)
                c1.metric("Keywords Found", metrics.get("optimized_count", 0), delta=f"+{len(metrics.get('newly_added', []))}")
                c2.metric("Total JD Keywords", metrics.get("total", 0))
                c3.metric("Match Score", f"{metrics.get('optimized_pct', 0)}%")
                
                st.progress(metrics.get("optimized_pct", 0) / 100)
            
            st.markdown("---")
            st.subheader("🤖 AI Optimization Report")
            st.info(st.session_state.get("changelog", "Detailed optimization results are ready."))
            
            if st.button("🔍 View Detailed Changes (Diff)", use_container_width=True):
                show_diff_dialog(st.session_state.resume_data, st.session_state.optimized_resume_data)
        else:
            st.info("💡 No optimized data found. You can run the AI Optimizer or paste an external JSON on the right.")

    with col_side:
        with st.container(border=True):
            st.subheader("📥 External Import")
            st.write("Paste the JSON result from ChatGPT/Claude here:")
            ext_json = st.text_area("Paste Full JSON Response", height=400, placeholder='{"heading": ..., "experience": ...}')
            
            if st.button("Apply External JSON", type="primary", use_container_width=True):
                if ext_json.strip():
                    try:
                        # 嘗試解析 JSON
                        parsed_json = json.loads(ext_json)
                        
                        # 處理可能嵌套在 "optimized_resume" 裡面的情況
                        if "optimized_resume" in parsed_json:
                            st.session_state.optimized_resume_data = parsed_json["optimized_resume"]
                        else:
                            st.session_state.optimized_resume_data = parsed_json
                            
                        # 如果有 ATS 數據也一併更新
                        if "keyword_analysis" in parsed_json:
                            st.session_state.ats_metrics = parsed_json["keyword_analysis"]
                        if "changelog" in parsed_json:
                            st.session_state.changelog = parsed_json["changelog"]
                            
                        st.success("✅ External JSON successfully applied!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ JSON Parsing Error: {e}")
                else:
                    st.warning("Please paste JSON content first.")
