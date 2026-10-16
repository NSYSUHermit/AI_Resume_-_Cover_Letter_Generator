"""Gemini calls and keyword scoring, with no Streamlit dependency.

Every function here takes plain arguments and returns plain data. Nothing reads
or writes session_state, so the same prompts can back a browser extension later
without two copies drifting apart.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor

import google.generativeai as genai
from google.api_core import exceptions as google_errors

# Used when nothing better is known: no key check has run yet (e.g. a key
# saved before model selection existed).
GEMINI_MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------
# 0. Which models a key can use
# ---------------------------------------------------------
# Free-tier keys cannot call every model - typically the newest ones are paid
# only - so a single hard-coded model locked new users out entirely. The key
# check below finds out what this particular key can actually run, and every
# call takes an ordered list of models to fall back through.

# Only the plain family ids: gemini-2.5-flash, gemini-3-pro-preview, ... Dated
# snapshots (-preview-09-2025), -001 pins, -latest aliases, and the image /
# TTS / live / embedding variants are left out, so a check sends a handful of
# requests rather than dozens.
_CANDIDATE_MODEL = re.compile(r"^gemini-(\d+(?:\.\d+)?)-(flash-lite|flash|pro)(-preview)?$")
# Flash first: two calls per Optimize on a free tier's small quota favours
# the fast model over Pro, and Flash-Lite keeps working when Flash is spent.
_TIER_RANK = {"flash": 0, "flash-lite": 1, "pro": 2}

# Errors that mean "this model cannot serve this key right now" - worth trying
# the next model. Anything else (a bad key, a malformed request) would fail the
# same way on every model, so it is raised at once.
_FALLBACK_ERRORS = (
    google_errors.ResourceExhausted,   # 429: quota spent, or no free tier at all
    google_errors.NotFound,            # 404: model retired or not offered to this key
    google_errors.ServiceUnavailable,  # 503: model overloaded
)
# A free-tier key calling a paid-only model gets a 429 whose quota line reads
# "limit: 0"; a key that merely spent its quota shows the real limit instead.
_NO_FREE_TIER = re.compile(r"limit:\s*0\b")

# Model check statuses. "busy" models are allowed on this key but out of quota
# or overloaded at the moment; they stay usable, just not first choice.
OK, BUSY, NOT_FREE, UNAVAILABLE = "ok", "busy", "not_free", "unavailable"
USABLE_STATUSES = (OK, BUSY)


class ModelsUnavailable(Exception):
    """Every model in the chain was out of quota, paid-only, retired or
    overloaded."""


def model_rank(name):
    """Sort key: stable before preview, Flash > Flash-Lite > Pro, newest first."""
    match = _CANDIDATE_MODEL.match(name)
    if not match:
        return (2, 9, 0.0)
    version, tier, preview = match.groups()
    return (1 if preview else 0, _TIER_RANK[tier], -float(version))


def _error_text(error):
    """The SDK's one-line message, not str(error)'s multi-line gRPC dump."""
    text = getattr(error, "message", None) or str(error) or type(error).__name__
    return text.strip().splitlines()[0][:200]


def _unavailable(error):
    """(status, human reason) for a failed call."""
    if isinstance(error, google_errors.ResourceExhausted):
        if _NO_FREE_TIER.search(str(error)):
            return NOT_FREE, "not on the free tier"
        return BUSY, "quota used up for now"
    if isinstance(error, google_errors.ServiceUnavailable):
        return BUSY, "overloaded right now"
    if isinstance(error, google_errors.NotFound):
        return UNAVAILABLE, "not available for this key"
    return UNAVAILABLE, _error_text(error)


def _model_chain(models):
    chain = []
    for model in models or ():
        if model and model not in chain:
            chain.append(model)
    return chain or [GEMINI_MODEL]


def _with_fallback(models, on_fallback, call):
    """Run `call(model)` on each model in turn until one accepts the request.

    `on_fallback(used, skipped)` is called only when the first choice was
    skipped: `used` is the model that answered, `skipped` a list of
    (model, reason) pairs for the ones before it.
    """
    skipped = []
    last_error = None
    for model in _model_chain(models):
        try:
            result = call(model)
        except _FALLBACK_ERRORS as e:
            skipped.append((model, _unavailable(e)[1]))
            last_error = e
            continue
        if skipped and on_fallback:
            on_fallback(model, skipped)
        return result
    tried = ", ".join(f"{m} ({reason})" for m, reason in skipped)
    raise ModelsUnavailable(
        f"No Gemini model could take this request: {tried}. "
        "Try another model, or try again later."
    ) from last_error


def _generate_json(api_key, parts, temperature=0.1, models=None, on_fallback=None):
    """Call Gemini in JSON mode and parse the response."""
    genai.configure(api_key=api_key)

    def call(model):
        response = genai.GenerativeModel(model).generate_content(
            parts,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": temperature,
            },
        )
        return json.loads(response.text)

    return _with_fallback(models, on_fallback, call)


def _generate_text(api_key, parts, temperature=0.3, models=None, on_fallback=None):
    """Call Gemini for prose and return the raw text.

    A separate function rather than a flag on _generate_json: that one pins
    response_mime_type to application/json, which is exactly wrong for an
    answer a human is about to paste into an application form. The default
    temperature differs for the same reason - 0.1 is right for extracting
    structure out of a document, and wooden for writing a paragraph about
    yourself.
    """
    genai.configure(api_key=api_key)

    def call(model):
        response = genai.GenerativeModel(model).generate_content(
            parts,
            generation_config={"temperature": temperature},
        )
        return response.text

    return _with_fallback(models, on_fallback, call)


def _probe_model(model):
    """One tiny request to `model`; returns a check result dict.

    The response body is deliberately not read: all that matters is whether
    the request was accepted.
    """
    try:
        genai.GenerativeModel(model).generate_content(
            "Reply with the single word: ok",
            generation_config={"temperature": 0, "max_output_tokens": 32},
            request_options={"timeout": 30},
        )
        return {"model": model, "status": OK, "reason": "works"}
    except Exception as e:
        status, reason = _unavailable(e)
        return {"model": model, "status": status, "reason": reason}


def check_models(api_key):
    """Find out which Gemini models this key can run.

    Returns (key_ok, message, results). key_ok is False when the key itself
    was rejected. results is one dict per candidate model - {"model",
    "status", "reason"} - in model_rank() order; status is OK, BUSY, NOT_FREE
    or UNAVAILABLE. Costs one tiny request per candidate, sent in parallel.
    """
    api_key = (api_key or "").strip()
    if not api_key:
        return False, "Paste a key first.", []
    try:
        genai.configure(api_key=api_key)
        names = {
            m.name.removeprefix("models/")
            for m in genai.list_models(request_options={"timeout": 20})
            if "generateContent" in (m.supported_generation_methods or ())
        }
    except Exception as e:
        return False, f"The key was rejected: {_error_text(e)}", []
    candidates = sorted((n for n in names if _CANDIDATE_MODEL.match(n)), key=model_rank)
    if not candidates:
        # Google renamed its models past what _CANDIDATE_MODEL expects; the
        # default is still the best guess there is.
        candidates = [GEMINI_MODEL]
    with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as pool:
        results = list(pool.map(_probe_model, candidates))
    usable = [r for r in results if r["status"] in USABLE_STATUSES]
    if not usable:
        return True, f"None of the {len(results)} models work with this key right now.", results
    return True, f"{len(usable)} of {len(results)} models work with this key.", results


def usable_models(results):
    """The models worth calling, in model_rank() order."""
    return [r["model"] for r in results if r["status"] in USABLE_STATUSES]


def recommended_model(results):
    """The best model that worked just now, else the best usable one, else None."""
    for status in USABLE_STATUSES:
        for r in results:
            if r["status"] == status:
                return r["model"]
    return None


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


def parse_resume_pdf(pdf_bytes, api_key, models=None, on_fallback=None):
    """Turn an uploaded resume PDF into the app's JSON structure."""
    return _generate_json(
        api_key,
        [PARSE_PROMPT, {"mime_type": "application/pdf", "data": pdf_bytes}],
        models=models, on_fallback=on_fallback,
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


def screen_job_description(jd_text, api_key, models=None, on_fallback=None):
    """Extract company, role, visa restrictions and the JD's keyword set.

    Separate from the rewrite so the rewrite call has one job, and so the
    keyword list comes from something other than the model grading its own work.
    """
    result = _generate_json(
        api_key, build_screening_prompt(jd_text), models=models, on_fallback=on_fallback
    )
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
  "changes": [
    {{ "path": "experience[0].details[1]", "reason": "one sentence: which JD requirement this change serves" }}
  ],
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

[CHANGES]
List one entry in "changes" for every field you rewrote, added or removed, so
the candidate can see why. "path" points into optimized_resume using its own
indexes: "summary", "experience[0].details[2]", "projects[1].description",
"patents[0].description", "skills.set1.items", "cover_letter". For content you
removed, use "removed:" plus its path in the ORIGINAL resume, e.g.
"removed:projects[3]". Each reason is one sentence naming the requirement in
the JD it serves.

[TARGET JD]
{jd_text}

[ORIGINAL RESUME]
{json.dumps(resume_data, ensure_ascii=False)}"""


def rewrite_resume(jd_text, resume_data, custom_prompt, api_key, models=None, on_fallback=None):
    result = _generate_json(
        api_key, build_rewrite_prompt(jd_text, resume_data, custom_prompt),
        models=models, on_fallback=on_fallback,
    )
    result.setdefault("changelog", "")
    result.setdefault("changes", [])
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
# 5. Application Q&A
# ---------------------------------------------------------

# Kept as a named constant, and pinned by tests/test_application_chat.py,
# because these rules ARE the feature. Everything around them is plumbing. A
# chat box that invents a metric has not been slightly unhelpful - it has put a
# lie on a job application under the candidate's own name, and the candidate
# will not find out until an interviewer asks about the number.
#
# Same principle as EVIDENCE_RULES above, applied to a different surface:
# EVIDENCE_RULES keeps the rewrite honest about the resume, this keeps the chat
# honest about everything else the candidate sends. Deliberately not shared -
# the rewrite's rules are written for a JSON transform ("record it in
# suggested_metrics"), which is meaningless advice to a chat turn, and the
# chat's rule 2 has to name a recovery the rewrite has no equivalent of (ask
# the candidate). Merging them would blunt both.
APPLICATION_CHAT_RULES = """You help this candidate answer questions that come up while they apply for a
job: free-text boxes on application forms, recruiter emails, screening
questions.

RULES:
1. Answer ONLY from the candidate data below. It is the whole truth you have
   about this person.
2. If answering would need a fact the data does not contain, DO NOT invent it.
   Say which specific fact is missing and ask the candidate for it. Never
   invent an employer, job title, date, duration, metric, tool, or technology.
3. Where the optimized resume already covers the same ground, reuse its
   wording, so the answer matches what the recruiter is reading.
4. Reply in the same language the question was asked in.
5. Default to a finished draft the candidate can paste straight into the form,
   not advice about how they should answer. Match the length the question
   implies, and skip the preamble."""

# Bounds cost and latency across a long session. The grounding blocks below are
# resent in full every turn regardless, so dropping old chatter costs very
# little accuracy - the resume and the JD are what the answers are built from,
# not the earlier questions.
MAX_CHAT_HISTORY = 20


def build_application_chat_prompt(messages, jd_text, resume_data, optimized_resume):
    """Assemble the whole prompt for one chat turn.

    Split out from answer_application_question() for the same reason
    build_screening_prompt() and build_rewrite_prompt() are split out from
    their callers: the prompt is the product here, so it has to be assertable
    without a network round trip.

    `messages` is the transcript so far as [{"role": "user"|"assistant",
    "content": str}], oldest first, INCLUDING the question being asked now.
    """
    transcript = "\n\n".join(
        f"{'CANDIDATE' if m.get('role') == 'user' else 'YOU'}: {m.get('content', '')}"
        for m in (messages or [])[-MAX_CHAT_HISTORY:]
    )
    # Spelled out rather than left empty: "(none yet)" tells the model the
    # absence is a normal state it should work around, where a blank block
    # invites it to assume the resume just failed to load.
    optimized_block = (
        json.dumps(optimized_resume, ensure_ascii=False)
        if optimized_resume
        else "(none yet - the candidate has not run an optimization for this job)"
    )
    return f"""{APPLICATION_CHAT_RULES}

[JOB DESCRIPTION]
{(jd_text or '').strip() or '(none provided)'}

[CANDIDATE PROFILE - their own source of truth]
{json.dumps(resume_data, ensure_ascii=False)}

[OPTIMIZED RESUME FOR THIS JOB]
{optimized_block}

[CONVERSATION SO FAR]
{transcript}

YOU:"""


def answer_application_question(messages, jd_text, resume_data, optimized_resume, api_key,
                                models=None, on_fallback=None):
    """One chat turn. Returns (ok, text).

    Reports the failure instead of swallowing it: a chat box that answers
    nothing and explains nothing is just broken, and the caller needs
    something to put in the bubble.
    """
    if not api_key:
        return False, "Connect a Gemini API key first."
    prompt = build_application_chat_prompt(messages, jd_text, resume_data, optimized_resume)
    try:
        reply = (_generate_text(api_key, prompt, models=models, on_fallback=on_fallback) or "").strip()
    except Exception as e:
        return False, str(e)
    if not reply:
        return False, "Gemini returned an empty answer. Try rephrasing the question."
    return True, reply
