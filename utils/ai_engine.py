import streamlit as st
import google.generativeai as genai
import json
import toml
import os

def load_prompts():
    """載入外部 Prompt 設定"""
    with open("prompts.toml", "r", encoding="utf-8") as f:
        return toml.load(f)

@st.cache_data(show_spinner=False)
def get_ai_response(api_key, model_name, prompt, pdf_bytes=None):
    """
    通用 AI 請求函數，具備快取功能。
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        if pdf_bytes:
            pdf_part = {"mime_type": "application/pdf", "data": pdf_bytes}
            response = model.generate_content([prompt, pdf_part])
        else:
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                )
            )
        
        return response.text.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def parse_pdf_resume(pdf_bytes, api_key, model_name):
    """解析 PDF 履歷為 JSON"""
    prompts = load_prompts()
    prompt = prompts['parsing']['system_prompt']
    
    raw_text = get_ai_response(api_key, model_name, prompt, pdf_bytes)
    
    if raw_text.startswith("ERROR:"):
        return False, raw_text, None
        
    try:
        # 清理可能存在的 Markdown 標籤
        clean_text = raw_text.replace('```json', '').replace('```', '').strip()
        parsed_json = json.loads(clean_text)
        return True, "✅ PDF parsed successfully!", parsed_json
    except json.JSONDecodeError as e:
        return False, f"⚠️ Malformed JSON from AI: {e}", None

def optimize_resume(jd_text, custom_prompt, enable_ats, check_visa, resume_data, api_key, model_name):
    """優化履歷內容"""
    prompts = load_prompts()
    opt_cfg = prompts['optimization']
    
    visa_instr = opt_cfg['visa_check_step'] if check_visa else "- Step 1: Disabled. Proceed to Step 2."
    ats_example = '"keyword_analysis": {"jd_keywords": ["..."], "original_hits": ["..."], "optimized_hits": ["..."], "newly_added": ["..."], "missing_keywords": []},' if enable_ats else ""
    
    final_prompt = opt_cfg['optimization_rules'].format(
        custom_prompt=custom_prompt,
        visa_check_instruction=visa_instr,
        jd_text=jd_text,
        resume_json=json.dumps(resume_data, ensure_ascii=False),
        ats_example=ats_example
    )
    
    raw_text = get_ai_response(api_key, model_name, final_prompt)
    
    if raw_text.startswith("ERROR:"):
        return False, raw_text
        
    try:
        ai_result = json.loads(raw_text)
        return True, ai_result
    except json.JSONDecodeError as e:
        return False, f"⚠️ Optimization result malformed: {e}"
