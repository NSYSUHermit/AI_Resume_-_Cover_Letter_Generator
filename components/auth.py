import streamlit as st
from firebase_dashboard import authenticate_user, register_user, save_user_profile, load_user_profile

def render_auth_sidebar(db):
    """處理側邊欄的登入與同步邏輯"""
    st.header("👤 Account")
    
    if st.session_state.get("logged_in"):
        st.success(f"Logged in as: {st.session_state.user_email}")

        if st.button("☁️ Sync Base Profile to Cloud"):
            if db:
                # 這裡抓取目前的配置並上傳
                current_prompt = st.session_state.get("opt_custom_prompt", "")
                current_api_key = st.session_state.get("api_key", "")
                success, msg = save_user_profile(
                    db, st.session_state.user_email, 
                    st.session_state.resume_data, 
                    current_prompt, 
                    current_api_key
                )
                if success: st.toast(msg)
                else: st.error(msg)
                    
        if st.button("⬇️ Pull Data from Cloud"):
            if db:
                loaded_resume, loaded_prompt, loaded_key = load_user_profile(db, st.session_state.user_email)
                if loaded_resume:
                    st.session_state.resume_data = loaded_resume
                    st.session_state.base_editor_key += 1
                    st.toast("✅ Base resume loaded from cloud.")
                if loaded_prompt:
                    st.session_state.custom_prompt = loaded_prompt
                if loaded_key:
                    st.session_state.api_key = loaded_key
                st.rerun()

        if st.button("🚪 Logout"):
            st.session_state.logged_in = False
            st.session_state.user_email = ""
            st.rerun()
            
    else:
        st.info("Log in to sync and track your job applications.")
        with st.form("login_form"):
            login_email = st.text_input("Email").strip()
            login_pwd = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                if db:
                    success, msg = authenticate_user(db, login_email, login_pwd)
                    if success:
                        st.session_state.logged_in = True
                        st.session_state.user_email = login_email
                        
                        # 自動載入雲端資料
                        loaded_resume, loaded_prompt, loaded_key = load_user_profile(db, login_email)
                        if loaded_resume:
                            st.session_state.resume_data = loaded_resume
                            st.session_state.base_editor_key += 1
                        if loaded_prompt: st.session_state.custom_prompt = loaded_prompt
                        if loaded_key: st.session_state.api_key = loaded_key
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.error("Firebase not connected.")

        with st.expander("📝 Register here"):
            with st.form("register_form"):
                reg_email = st.text_input("Email").strip()
                reg_pwd = st.text_input("Password", type="password")
                reg_pwd_confirm = st.text_input("Confirm Password", type="password")
                if st.form_submit_button("Register"):
                    if reg_pwd != reg_pwd_confirm:
                        st.error("Passwords do not match!")
                    else:
                        success, msg = register_user(db, reg_email, reg_pwd)
                        if success: st.success(msg)
                        else: st.error(msg)
