import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================
# 1. 初始化與連接 Firebase
# ==========================================
def init_firebase():
    """
    初始化 Firebase Admin SDK。
    利用 firebase_admin._apps 檢查是否已初始化，避免 Streamlit 重新執行時報錯。
    """
    if not firebase_admin._apps:
        try:
            # 從 Streamlit Secrets 讀取 Firebase 服務帳戶的 JSON 配置
            cert_dict = dict(st.secrets["firebase_service_account"])
            cred = credentials.Certificate(cert_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"❌ Firebase 初始化失敗: {e}")
            return None
    
    # 返回 Firestore 客戶端實例
    return firestore.client()

# ==========================================
# 2. 儲存申請紀錄
# ==========================================
def save_application(db, email: str, company_name: str, resume_json: dict):
    """
    將使用者的求職紀錄儲存至 Firestore。
    路徑: users/{email}/applications/{auto_id}
    """
    try:
        # 取得目標 Collection 的 Reference，並自動產生一個新 Document
        doc_ref = db.collection('users').document(email).collection('applications').document()
        
        data = {
            "company_name": company_name,
            "applied_date": firestore.SERVER_TIMESTAMP, # 使用伺服器時間，確保時區一致
            "status": "Applied",
            "resume_json": resume_json,
            "interview_date": None,
            "rejected_date": None
        }
        
        doc_ref.set(data)
        return True
    except Exception as e:
        st.error(f"❌ 儲存申請紀錄時發生錯誤: {e}")
        return False

# ==========================================
# 3. & 4. 讀取、更新與顯示 Dashboard 邏輯
# ==========================================
def update_application_status(db, email: str, doc_id: str, new_status: str):
    """
    根據傳入的新狀態更新 Document，並自動填寫對應的時間戳記。
    """
    try:
        doc_ref = db.collection('users').document(email).collection('applications').document(doc_id)
        update_data = {"status": new_status}
        
        # 狀態控制：自動寫入當下時間
        if new_status == "Interviewing":
            update_data["interview_date"] = firestore.SERVER_TIMESTAMP
        elif new_status == "Rejected":
            update_data["rejected_date"] = firestore.SERVER_TIMESTAMP
            
        doc_ref.update(update_data)
        return True
    except Exception as e:
        st.error(f"❌ 更新狀態時發生錯誤: {e}")
        return False

def render_dashboard(db, email: str):
    """
    讀取該 email 下的所有申請紀錄，並以時間倒序渲染 Streamlit Dashboard。
    """
    st.subheader("📊 你的求職申請紀錄 (Job Applications)")
    
    try:
        # 抓取紀錄並以 applied_date 倒序排列 (最新的在最上面)
        apps_ref = db.collection('users').document(email).collection('applications')
        query = apps_ref.order_by('applied_date', direction=firestore.Query.DESCENDING)
        docs = query.stream()
        
        has_records = False
        for doc in docs:
            has_records = True
            app_data = doc.to_dict()
            doc_id = doc.id
            
            company = app_data.get("company_name", "Unknown")
            status = app_data.get("status", "Applied")
            
            # 處理時間顯示格式
            applied_date = app_data.get("applied_date")
            date_str = applied_date.strftime("%Y-%m-%d %H:%M") if applied_date else "N/A"
            
            # 狀態對應的 Emoji (UI 優化)
            status_emoji = {"Applied": "📤", "Interviewing": "💬", "Rejected": "💔"}.get(status, "📄")
            
            # 使用 Expander 展示每一筆申請紀錄
            with st.expander(f"{status_emoji} {company} - {status} ({date_str})"):
                st.write(f"**投遞時間:** {date_str}")
                
                # 顯示面試/拒絕時間 (若有)
                if app_data.get("interview_date"):
                    st.write(f"**面試時間:** {app_data['interview_date'].strftime('%Y-%m-%d %H:%M')}")
                if app_data.get("rejected_date"):
                    st.write(f"**拒絕時間:** {app_data['rejected_date'].strftime('%Y-%m-%d %H:%M')}")
                
                st.divider()
                
                # 狀態更新 UI
                col1, col2 = st.columns([3, 1])
                with col1:
                    # 下拉選單供使用者選擇新狀態
                    options = ["Applied", "Interviewing", "Rejected"]
                    current_idx = options.index(status) if status in options else 0
                    new_status = st.selectbox("更新狀態:", options, index=current_idx, key=f"select_{doc_id}")
                
                with col2:
                    st.write("") # 排版對齊用
                    st.write("")
                    # 只有當狀態改變時才觸發更新
                    if st.button("更新", key=f"btn_{doc_id}", use_container_width=True):
                        if new_status != status:
                            if update_application_status(db, email, doc_id, new_status):
                                st.success("✅ 狀態已更新！")
                                st.rerun() # 重新刷新畫面以顯示最新資料
        if not has_records:
            st.info("目前還沒有任何求職紀錄哦，趕快去投遞你的第一份履歷吧！🚀")
            
    except Exception as e:
        st.error(f"❌ 讀取 Dashboard 失敗: {e}")