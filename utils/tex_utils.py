import re

def escape_tex(text):
    """
    更完整的 LaTeX 特殊字元轉義邏輯。
    """
    if not isinstance(text, str):
        return str(text)
    
    # 定義轉義對照表
    tex_conversions = {
        '\\': r'\textbackslash{}',
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    
    # 優先處理反斜線，避免重複轉義
    text = text.replace('\\', tex_conversions['\\'])
    
    # 處理其他字元
    for char, escaped in tex_conversions.items():
        if char != '\\':
            text = text.replace(char, escaped)
            
    # 處理特殊符號
    text = text.replace('<', r'\textless{}')
    text = text.replace('>', r'\textgreater{}')
    text = text.replace('|', r'\textbar{}')
    
    return text

def clean_json_for_tex(data):
    """
    遞迴處理 JSON 資料，將所有字串進行 LaTeX 轉義，並移除 Markdown 加粗符號。
    """
    if isinstance(data, dict):
        return {k: clean_json_for_tex(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_json_for_tex(i) for i in data]
    elif isinstance(data, str):
        # 移除 AI 常見的 Markdown 加粗 **
        clean_text = data.replace('**', '')
        return escape_tex(clean_text)
    return data
