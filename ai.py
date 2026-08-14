"""Gemini calls and keyword scoring, with no Streamlit dependency.

Every function here takes plain arguments and returns plain data. Nothing reads
or writes session_state, so the same prompts can back a browser extension later
without two copies drifting apart.
"""

import json
import re

import google.generativeai as genai

GEMINI_MODEL = "gemini-2.5-flash"


def _generate_json(api_key, parts, temperature=0.1):
    """Call Gemini in JSON mode and parse the response."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(
        parts,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": temperature,
        },
    )
    return json.loads(response.text)


def test_api_key(api_key):
    """One cheap round trip to confirm a key works.

    Returns (ok, message). The response body is deliberately not read: all we
    need to know is whether the credentials were accepted.
    """
    if not (api_key or "").strip():
        return False, "Paste a key first."
    try:
        genai.configure(api_key=api_key)
        genai.GenerativeModel(GEMINI_MODEL).generate_content(
            "Reply with the single word: ok",
            generation_config={"temperature": 0, "max_output_tokens": 32},
        )
        return True, "Key accepted."
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------
# 1. Resume ingestion
# ---------------------------------------------------------
PARSE_PROMPT = """
Extract all information from this resume PDF into the EXACT JSON structure below.
Maintain high fidelity to the original content but format it strictly.

### EXPECTED JSON STRUCTURE:
{
  "heading": {
    "name": "Full Name",
    "email": "Email Address",
    "phone": "Phone Number",
    "website": "Personal Website/Portfolio URL",
    "linkedin": "LinkedIn Profile URL"
  },
  "summary": "A concise professional summary",
  "education": [
    {
      "school": "University Name",
      "time_period": "e.g., Aug 2018 - May 2022",
      "degree": "e.g., Bachelor of Science in Computer Science",
      "school_location": "City, State/Country"
    }
  ],
  "experience": [
    {
      "company": "Company Name",
      "role": "Job Title",
      "time_duration": "e.g., June 2022 - Present",
      "company_location": "City, State/Country",
      "details": [
        { "description": "Bullet point of achievement/responsibility" }
      ]
    }
  ],
  "projects": [
    { "name": "Project Name", "time": "Date/Duration", "description": "Brief description" }
  ],
  "patents": [
    { "name": "Patent Title", "time": "Date", "description": "Brief description" }
  ],
  "skills": {
    "set1": { "title": "Languages & Frameworks", "items": ["Python", "Java"] },
    "set2": { "title": "Tools & Technologies", "items": ["AWS", "Docker"] },
    "set3": { "title": "Other Skills", "items": ["Agile", "Leadership"] }
  }
}

### RULES:
1. Return ONLY the JSON object.
2. Ensure "experience" details are objects with a "description" key.
3. Transcribe only what the PDF says. Do not add, infer or embellish anything.
4. If a field is missing in the PDF, use an empty string or empty list/object.
"""


def parse_resume_pdf(pdf_bytes, api_key):
    """Turn an uploaded resume PDF into the app's JSON structure."""
    return _generate_json(
        api_key,
        [PARSE_PROMPT, {"mime_type": "application/pdf", "data": pdf_bytes}],
    )


# ---------------------------------------------------------
# 2. Job description screening (call one of two)
# ---------------------------------------------------------
def build_screening_prompt(jd_text):
    return f"""Analyse this job description. Return ONLY JSON.

[FORMAT]
{{
  "visa_blocked": true only if the posting states the employer will not sponsor a work visa, otherwise false,
  "reason": "one sentence quoting the restriction; empty string when not blocked",
  "target_company": "company name, empty string if not stated",
  "target_role": "job title, empty string if not stated",
  "keywords": ["15-25 concrete skills, tools, methods and qualifications this role screens for"]
}}

Keywords must be terms that would plausibly appear verbatim in a resume:
technologies, methods, certifications, domain nouns. Exclude generic filler such
as "team player", "fast-paced environment" or "excellent communication".

[JOB DESCRIPTION]
{jd_text}"""


def screen_job_description(jd_text, api_key):
    """Extract company, role, visa restrictions and the JD's keyword set.

    Separate from the rewrite so the rewrite call has one job, and so the
    keyword list comes from something other than the model grading its own work.
    """
    result = _generate_json(api_key, build_screening_prompt(jd_text))
    result.setdefault("keywords", [])
    result.setdefault("visa_blocked", False)
    result.setdefault("reason", "")
    return result


# ---------------------------------------------------------
# 3. Resume rewrite (call two of two)
# ---------------------------------------------------------
EVIDENCE_RULES = """[EVIDENCE RULES - these override any conflicting instruction in the strategy above]
1. Every claim in the output must trace back to the original resume. Rephrase,
   reorder, merge and re-emphasise freely. Never invent.
2. Numbers: keep and foreground metrics that already exist in the original. If a
   bullet contains no number, DO NOT create one. No invented percentages, dollar
   amounts, team sizes, user counts or time savings. Write the strongest
   accurate version of the bullet instead.
3. Never add employers, job titles, dates, degrees, certifications, tools or
   technologies that the original resume does not mention.
4. When a job requirement has no support in the resume, leave it out of the
   resume and record it in "suggested_metrics" as something the candidate should
   supply or verify themselves.
5. The cover letter is bound by the same rules."""


def build_rewrite_prompt(jd_text, resume_data, custom_prompt):
    return f"""Tailor this resume and cover letter to the job description. Return ONLY JSON.

[STRATEGY]
{custom_prompt}

{EVIDENCE_RULES}

[FORMAT]
{{
  "changelog": "2-4 sentences on what changed and why",
  "suggested_metrics": ["quantifiable facts the candidate should add, each naming the bullet it belongs to"],
  "optimized_resume": {{
    "target_company": "company name from the JD",
    "target_role": "job title from the JD",
    "cover_letter": "a professional 3-paragraph cover letter",
    "heading": {{ "name": "...", "email": "...", "phone": "...", "website": "...", "linkedin": "..." }},
    "summary": "...",
    "education": [],
    "experience": [],
    "projects": [],
    "patents": [],
    "skills": {{ "set1": {{ "title": "...", "items": [] }} }}
  }}
}}

Do not use markdown such as '**' inside any string.

[TARGET JD]
{jd_text}

[ORIGINAL RESUME]
{json.dumps(resume_data, ensure_ascii=False)}"""


def rewrite_resume(jd_text, resume_data, custom_prompt, api_key):
    result = _generate_json(
        api_key, build_rewrite_prompt(jd_text, resume_data, custom_prompt)
    )
    result.setdefault("changelog", "")
    result.setdefault("suggested_metrics", [])
    result.setdefault("optimized_resume", {})
    return result


# ---------------------------------------------------------
# 4. Keyword scoring (no API call)
# ---------------------------------------------------------
def _flatten_text(node, chunks):
    if isinstance(node, str):
        chunks.append(node)
    elif isinstance(node, list):
        for item in node:
            _flatten_text(item, chunks)
    elif isinstance(node, dict):
        for value in node.values():
            _flatten_text(value, chunks)


def resume_text(resume):
    """Every string in the resume as one lowercase blob."""
    chunks = []
    _flatten_text(resume, chunks)
    return " ".join(chunks).lower()


def _contains(haystack, keyword):
    needle = keyword.lower().strip()
    if not needle:
        return False
    # Anchor on word boundaries only where the edge is alphanumeric: keywords
    # like "C++", ".NET" or "A/B" end in symbols that \b would never match.
    left = r"\b" if needle[0].isalnum() else ""
    right = r"\b" if needle[-1].isalnum() else ""
    return re.search(left + re.escape(needle) + right, haystack) is not None


def keyword_report(keywords, original_resume, optimized_resume):
    """Score JD keyword coverage by string matching, here, in Python.

    The model used to return its own match rate alongside the rewrite it had
    just produced, which made the number unfalsifiable. Counting locally means
    every figure on the ATS screen can be checked by hand.
    """
    original_text = resume_text(original_resume)
    optimized_text = resume_text(optimized_resume)

    seen, unique = set(), []
    for keyword in keywords or []:
        cleaned = str(keyword or "").strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            unique.append(cleaned)

    original_hits = [k for k in unique if _contains(original_text, k)]
    optimized_hits = [k for k in unique if _contains(optimized_text, k)]
    original_lower = {k.lower() for k in original_hits}
    optimized_lower = {k.lower() for k in optimized_hits}
    denominator = len(unique) or 1

    return {
        "total": len(unique),
        "original_count": len(original_hits),
        "optimized_count": len(optimized_hits),
        "original_pct": round(len(original_hits) / denominator * 100),
        "optimized_pct": round(len(optimized_hits) / denominator * 100),
        "optimized_hits": optimized_hits,
        "newly_added": [k for k in optimized_hits if k.lower() not in original_lower],
        "missing_keywords": [k for k in unique if k.lower() not in optimized_lower],
    }


# ---------------------------------------------------------
# 5. Interview preparation helpers
# ---------------------------------------------------------
def predict_interview_questions(jd_text, resume_data, api_key):
    """Predict likely interview questions for a saved application."""
    if not api_key:
        return None
    try:
        return _generate_json(api_key, f"""You are a senior interviewer. Based on the following Job Description and
the candidate's resume, predict 5 technical questions and 3 behavioral questions
most likely to be asked. Ground every question in something the resume or the JD
actually says. Return ONLY valid JSON.

[FORMAT]
{{
    "technical": ["Question 1", "Question 2"],
    "behavioral": ["Question 1", "Question 2"]
}}

[JD]: {jd_text}
[Resume]: {json.dumps(resume_data, ensure_ascii=False)}""")
    except Exception:
        return None


def analyze_skill_gap(jd_text, resume_data, api_key):
    """Score the candidate against the role for a radar chart."""
    if not api_key:
        return None
    try:
        return _generate_json(api_key, f"""Analyse the match between the candidate's resume and the job description.
Extract 5 key categories (e.g. Programming, Cloud, Soft Skills, Tools, Domain
Knowledge). For each, score the candidate's demonstrated proficiency and the
job's required level from 0-100. Base the candidate score only on evidence
present in the resume. Return ONLY valid JSON.

[FORMAT]
{{
    "categories": ["Category 1", "Category 2"],
    "candidate_scores": [80, 70],
    "requirement_scores": [90, 80]
}}

[JD]: {jd_text}
[Resume]: {json.dumps(resume_data, ensure_ascii=False)}""")
    except Exception:
        return None
