import streamlit as st
import base64

def get_glass_overlay_html(message, animal_emoji, theme_color):
    """回傳 Glassmorphism 動畫 HTML"""
    return f"""<style>
.glass-overlay-bg {{
    position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    background: rgba(10, 10, 15, 0.7);
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    z-index: 999999; display: flex; justify-content: center; align-items: center;
}}
.glass-dialog-box {{
    background: linear-gradient(135deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.01));
    border: 1px solid rgba(255, 255, 255, 0.1);
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    border-radius: 24px; padding: 50px 60px;
    text-align: center; position: relative; overflow: hidden;
    display: flex; flex-direction: column; align-items: center;
}}
.float-container {{
    animation: floatAnim 2.5s ease-in-out infinite;
    margin-bottom: 10px; z-index: 2; position: relative;
}}
.interactive-animal {{
    font-size: 85px; user-select: none; display: inline-block;
}}
@keyframes floatAnim {{ 0%, 100% {{ transform: translateY(0px); }} 50% {{ transform: translateY(-15px); }} }}
.loading-text {{
    color: #ffffff; font-family: 'Segoe UI', sans-serif; font-size: 1.2rem;
    font-weight: 300; letter-spacing: 1px; margin: 0;
}}
</style>
<div class="glass-overlay-bg">
    <div class="glass-dialog-box">
        <div class="float-container">
            <div class="interactive-animal">{animal_emoji}</div>
        </div>
        <h2 class="loading-text">{message}</h2>
    </div>
</div>"""

def show_copy_button(text, label="📋 Copy to Clipboard"):
    """顯示一個美化的複製按鈕"""
    b64_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')
    html_code = f"""
    <button onclick="copyText()" style="padding: 10px; border-radius: 5px; cursor: pointer; width: 100%;">
        {label}
    </button>
    <script>
    function copyText() {{
        const text = decodeURIComponent(escape(window.atob('{b64_text}')));
        navigator.clipboard.writeText(text);
        alert('Copied!');
    }}
    </script>
    """
    st.components.v1.html(html_code, height=50)
