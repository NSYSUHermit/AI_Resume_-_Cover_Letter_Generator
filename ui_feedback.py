import json
import time

import streamlit as st
import streamlit.components.v1 as components


def is_ai_busy():
    return st.session_state.get("ai_busy", False)


def render_ai_wait_panel(title, stages):
    """Render a lightweight client-side wait panel with timer and tiny interaction."""
    title_json = json.dumps(title)
    stages_json = json.dumps(stages)
    components.html(
        f"""
        <!doctype html>
        <html>
        <head>
          <style>
            :root {{
              --brand: #2563eb;
              --ink: #111827;
              --muted: #64748b;
              --line: #dbeafe;
              --soft: #eff6ff;
              --ok: #059669;
            }}
            body {{
              margin: 0;
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              color: var(--ink);
              background: transparent;
            }}
            .panel {{
              border: 1px solid var(--line);
              border-radius: 8px;
              background:
                radial-gradient(circle at 12% 20%, rgba(37,99,235,0.12), transparent 28%),
                linear-gradient(135deg, #ffffff 0%, var(--soft) 100%);
              padding: 18px 20px;
              box-shadow: 0 12px 28px rgba(15, 23, 42, 0.10);
              overflow: hidden;
            }}
            .top {{
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 12px;
            }}
            .title {{
              font-weight: 750;
              font-size: 16px;
              letter-spacing: 0;
            }}
            .time {{
              font-variant-numeric: tabular-nums;
              color: var(--brand);
              font-weight: 750;
            }}
            .stage {{
              margin-top: 10px;
              color: var(--muted);
              min-height: 22px;
            }}
            .bar {{
              margin-top: 14px;
              height: 8px;
              border-radius: 999px;
              background: #dbeafe;
              overflow: hidden;
            }}
            .fill {{
              width: 8%;
              height: 100%;
              border-radius: inherit;
              background: linear-gradient(90deg, var(--brand), var(--ok));
              transition: width 600ms ease;
            }}
            .orbit {{
              display: flex;
              gap: 7px;
              margin-top: 16px;
            }}
            .dot {{
              width: 10px;
              height: 10px;
              border-radius: 50%;
              background: var(--brand);
              opacity: 0.4;
              animation: pulse 1.2s ease-in-out infinite;
            }}
            .dot:nth-child(2) {{ animation-delay: 0.18s; }}
            .dot:nth-child(3) {{ animation-delay: 0.36s; }}
            .dot:nth-child(4) {{ animation-delay: 0.54s; }}
            @keyframes pulse {{
              0%, 100% {{ transform: translateY(0); opacity: 0.35; }}
              50% {{ transform: translateY(-6px); opacity: 1; }}
            }}
            .bottom {{
              margin-top: 14px;
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 12px;
            }}
            .note {{
              color: var(--muted);
              font-size: 12px;
            }}
            button {{
              border: 1px solid var(--line);
              border-radius: 8px;
              background: white;
              color: var(--ink);
              font-weight: 650;
              min-height: 34px;
              padding: 0 12px;
              cursor: pointer;
              transition: transform 160ms ease, border-color 160ms ease, color 160ms ease;
            }}
            button:hover {{
              transform: translateY(-1px);
              border-color: var(--brand);
              color: var(--brand);
            }}
            .spark {{
              display: inline-block;
              margin-left: 6px;
              color: var(--ok);
              font-variant-numeric: tabular-nums;
            }}
          </style>
        </head>
        <body>
          <div class="panel">
            <div class="top">
              <div class="title" id="title"></div>
              <div class="time" id="elapsed">00:00</div>
            </div>
            <div class="stage" id="stage"></div>
            <div class="bar"><div class="fill" id="fill"></div></div>
            <div class="orbit">
              <div class="dot"></div><div class="dot"></div><div class="dot"></div><div class="dot"></div>
            </div>
            <div class="bottom">
              <div class="note">Workflow status only. Model reasoning stays private.</div>
              <button id="checkpoint" type="button">Mark checkpoint <span class="spark" id="count">0</span></button>
            </div>
          </div>
          <script>
            const title = {title_json};
            const stages = {stages_json};
            const start = Date.now();
            let count = 0;
            document.getElementById("title").textContent = title;
            document.getElementById("checkpoint").addEventListener("click", () => {{
              count += 1;
              document.getElementById("count").textContent = count;
            }});
            function draw() {{
              const seconds = Math.floor((Date.now() - start) / 1000);
              const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
              const ss = String(seconds % 60).padStart(2, "0");
              const stageIndex = Math.min(stages.length - 1, Math.floor(seconds / 6));
              const progress = Math.min(92, 10 + seconds * 1.8);
              document.getElementById("elapsed").textContent = `${{mm}}:${{ss}}`;
              document.getElementById("stage").textContent = stages[stageIndex] || "Working...";
              document.getElementById("fill").style.width = `${{progress}}%`;
            }}
            draw();
            setInterval(draw, 250);
          </script>
        </body>
        </html>
        """,
        height=230,
    )


def lock_app_controls():
    st.markdown(
        """
        <style>
          [data-testid="stAppViewContainer"] button,
          [data-testid="stAppViewContainer"] input,
          [data-testid="stAppViewContainer"] textarea,
          [data-testid="stAppViewContainer"] [role="button"],
          [data-testid="stAppViewContainer"] [role="radio"],
          [data-testid="stAppViewContainer"] [role="checkbox"],
          [data-testid="stAppViewContainer"] [role="combobox"],
          [data-testid="stSidebar"] button,
          [data-testid="stSidebar"] input,
          [data-testid="stSidebar"] textarea,
          [data-testid="stSidebar"] [role="button"],
          [data-testid="stSidebar"] [role="radio"],
          [data-testid="stSidebar"] [role="checkbox"],
          [data-testid="stSidebar"] [role="combobox"] {
            pointer-events: none !important;
          }
          [data-testid="stAppViewContainer"] button,
          [data-testid="stSidebar"] button {
            opacity: 0.55 !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def run_ai_call(title, stages, fn):
    st.session_state.ai_busy = True
    lock_app_controls()
    render_ai_wait_panel(title, stages)
    time.sleep(0.1)
    try:
        return fn()
    finally:
        st.session_state.ai_busy = False
