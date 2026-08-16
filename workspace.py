"""Pure decision logic for the three-view workspace.

This lives outside app.py because app.py is a top-level Streamlit script:
importing it executes the entire UI, so none of the rules below could be
tested in place. Nothing here may import streamlit.
"""

PROFILE = "Profile"
GENERATOR = "Generator"
TRACKER = "Tracker"

# (active_view value, sidebar label, material icon)
VIEWS = (
    (PROFILE, "Career Profile", ":material/person:"),
    (GENERATOR, "Generator", ":material/auto_awesome:"),
    (TRACKER, "Tracker", ":material/monitoring:"),
)

# Matches the threshold the old workspace bar used: a couple of words pasted by
# accident is not a job description.
_JD_MIN_LENGTH = 50


def initial_view(resume_is_empty):
    """Where a session lands before the user navigates anywhere.

    New users have nothing to generate from, so they start on the profile.
    Returning users came back to send another application.
    """
    return PROFILE if resume_is_empty else GENERATOR


def application_progress(jd_text, has_optimized, has_pdf, is_tracked):
    """The four stages of one application, as (label, done) pairs.

    Returned in the order they happen; the caller just renders the list.
    """
    return [
        ("Job description added", len(jd_text or "") > _JD_MIN_LENGTH),
        ("Resume optimized", bool(has_optimized)),
        ("PDF generated", bool(has_pdf)),
        ("Saved to tracker", bool(is_tracked)),
    ]


def should_record_application(is_tracked, logged_in):
    """Whether a download should write a new tracker row.

    save_application() writes with an auto-generated document id and does no
    deduplication at all, so without this guard a user who downloads the resume
    and then the cover letter — or who just downloads twice — gets one tracker
    row per click. One optimize run is one application.
    """
    return bool(logged_in) and not is_tracked


# Tracker status -> which theme.TOKENS colour name the sidebar's status dot
# should use for that row. Only the token *name* lives here, not a colour
# value: this module may not import theme (or streamlit) - see the module
# docstring - so app.py is the one that turns e.g. "success" into
# var(--success) in the stylesheet.
_STATUS_DOT_TOKENS = {
    "Applied": "brand",
    "Interviewing": "warning",
    "Offered": "success",
    "Rejected": "danger",
}
_DEFAULT_STATUS_DOT_TOKEN = "muted"


def recent_applications(records, limit=3):
    """Up to `limit` tracker rows, reshaped for the sidebar's compact list.

    `records` is whatever firebase_dashboard.fetch_applications() returned -
    already newest-first, since the Firestore query itself orders by
    applied_date descending - so this only takes a prefix; it does no
    sorting of its own and trusts the caller's ordering.

    Company/role fall back the same way firebase_dashboard.render_dashboard()
    already displays them (company defaults to "Unknown"; role has no
    top-level field of its own, it lives in resume_json.target_role, and
    defaults to "" so the caller can drop it from the row entirely) - a
    sidebar row and the full Tracker view should never disagree about what an
    incomplete record shows.
    """
    rows = []
    for record in (records or [])[:limit]:
        record = record or {}
        status = record.get("status") or "Applied"
        rows.append({
            "company": record.get("company_name") or "Unknown",
            "role": (record.get("resume_json") or {}).get("target_role") or "",
            "status_dot_token": _STATUS_DOT_TOKENS.get(status, _DEFAULT_STATUS_DOT_TOKEN),
        })
    return rows
