"""review.py: what the AI rewrite changed, and applying the user's edits.

The change list is computed locally by comparing the Career Profile with the
optimized resume - never taken from the model's own account - so it cannot
list a change that did not happen or miss one the model forgot to mention.
The model only supplies the "why", matched to each change by path.
"""
import review

ORIGINAL = {
    "summary": "Backend engineer.",
    "experience": [
        {"company": "Acme", "role": "Engineer", "details": [
            {"description": "Built APIs in Python"},
            {"description": "Ran on-call rotation"},
            {"description": "Mentored two interns"},
        ]},
        {"company": "Globex", "role": "Intern", "details": [{"description": "Wrote tests"}]},
    ],
    "projects": [
        {"name": "Parser", "time": "2021", "description": "A JSON parser"},
        {"name": "Old Game", "time": "2019", "description": "A browser game"},
    ],
    "patents": [],
    "skills": {"set1": {"title": "Languages", "items": ["Python", "Go"]}},
    "cover_letter": "",
}

OPTIMIZED = {
    "target_company": "Initech",
    "summary": "Backend engineer focused on high-traffic Python APIs.",
    "experience": [
        {"company": "Acme", "role": "Engineer", "details": [
            {"description": "Mentored two interns"},
            {"description": "Built high-traffic REST APIs in Python"},
            {"description": "Ran the on-call rotation for payment services"},
        ]},
        {"company": "Globex", "role": "Intern", "details": [{"description": "Wrote tests"}]},
    ],
    "projects": [{"name": "Parser", "time": "2021", "description": "A streaming JSON parser in Python"}],
    "patents": [],
    "skills": {"set1": {"title": "Languages", "items": ["Python", "Go", "SQL"]}},
    "cover_letter": "Dear Initech team, ...",
}

REASONS = [
    {"path": "summary", "reason": "The JD asks for high-traffic API experience."},
    {"path": "experience[0].details[1]", "reason": "Names REST, which the JD lists."},
    {"path": "experience[0].details[2].description", "reason": "Payments is the team's domain."},
    {"path": "removed:projects[1]", "reason": "Unrelated to backend work."},
]


def by_id(changes):
    return {c["id"]: c for c in changes}


def test_lists_only_what_actually_changed():
    changes = by_id(review.collect_changes(ORIGINAL, OPTIMIZED, REASONS))
    assert set(changes) == {
        "summary",
        "experience.0.details.1",
        "experience.0.details.2",
        "projects.0.description",
        "removed:projects.1",
        "skills.set1.items",
        "cover_letter",
    }
    # Reordered but untouched bullets ("Mentored two interns") and the
    # untouched Globex entry are not changes.


def test_reordered_bullets_are_paired_with_their_original():
    changes = by_id(review.collect_changes(ORIGINAL, OPTIMIZED, REASONS))
    bullet = changes["experience.0.details.1"]
    assert bullet["kind"] == review.EDITED
    assert bullet["before"] == "Built APIs in Python"
    assert bullet["after"] == "Built high-traffic REST APIs in Python"
    assert bullet["group"] == "Experience · Acme — Engineer"
    assert changes["experience.0.details.2"]["before"] == "Ran on-call rotation"


def test_reasons_are_matched_by_path_in_either_spelling():
    changes = by_id(review.collect_changes(ORIGINAL, OPTIMIZED, REASONS))
    assert changes["summary"]["reason"] == "The JD asks for high-traffic API experience."
    assert changes["experience.0.details.1"]["reason"] == "Names REST, which the JD lists."
    assert changes["experience.0.details.2"]["reason"] == "Payments is the team's domain."
    assert changes["removed:projects.1"]["reason"] == "Unrelated to backend work."
    # No reason given: still listed, just without one.
    assert changes["projects.0.description"]["reason"] == ""


def test_an_entry_level_reason_covers_its_bullets():
    reasons = [{"path": "experience[0]", "reason": "Reframed Acme around APIs."}]
    changes = by_id(review.collect_changes(ORIGINAL, OPTIMIZED, reasons))
    assert changes["experience.0.details.1"]["reason"] == "Reframed Acme around APIs."


def test_removed_and_added_content():
    changes = by_id(review.collect_changes(ORIGINAL, OPTIMIZED, REASONS))
    removed = changes["removed:projects.1"]
    assert removed["kind"] == review.REMOVED
    assert removed["before"] == "Old Game — A browser game"
    assert removed["after"] is None
    letter = changes["cover_letter"]
    assert letter["kind"] == review.ADDED
    assert letter["before"] is None


def test_skills_are_edited_as_one_comma_separated_line():
    skills = by_id(review.collect_changes(ORIGINAL, OPTIMIZED, []))["skills.set1.items"]
    assert skills["is_list"]
    assert skills["before"] == "Python, Go"
    assert skills["after"] == "Python, Go, SQL"


def test_changes_come_in_resume_order():
    ids = [c["id"] for c in review.collect_changes(ORIGINAL, OPTIMIZED, REASONS)]
    assert ids == [
        "summary",
        "experience.0.details.1",
        "experience.0.details.2",
        "projects.0.description",
        "removed:projects.1",
        "skills.set1.items",
        "cover_letter",
    ]


def test_unusable_input_yields_no_changes():
    assert review.collect_changes(ORIGINAL, "not a dict", REASONS) == []
    assert review.collect_changes(None, {"summary": "x"}, None)[0]["kind"] == review.ADDED
    # A model that sent junk instead of a list of reasons costs only the reasons.
    assert review.collect_changes(ORIGINAL, OPTIMIZED, "junk")[0]["reason"] == ""


def test_identical_resumes_have_no_changes():
    assert review.collect_changes(ORIGINAL, ORIGINAL, []) == []


# --- applying edits --------------------------------------------------------------

def test_apply_edits_writes_each_path_and_leaves_the_input_alone():
    changes = by_id(review.collect_changes(ORIGINAL, OPTIMIZED, REASONS))
    edits = {
        changes["summary"]["path"]: "Edited summary.",
        changes["experience.0.details.1"]["path"]: "Edited bullet",
        changes["skills.set1.items"]["path"]: "Python,  Go , ,Rust",
    }
    updated = review.apply_edits(OPTIMIZED, edits)
    assert updated["summary"] == "Edited summary."
    assert updated["experience"][0]["details"][1] == {"description": "Edited bullet"}
    assert updated["skills"]["set1"]["items"] == ["Python", "Go", "Rust"]
    assert OPTIMIZED["summary"] == "Backend engineer focused on high-traffic Python APIs."


def test_restoring_removed_content_appends_it():
    changes = by_id(review.collect_changes(ORIGINAL, OPTIMIZED, REASONS))
    updated = review.apply_edits(OPTIMIZED, {}, restores=[changes["removed:projects.1"]])
    assert [p["name"] for p in updated["projects"]] == ["Parser", "Old Game"]


def test_restoring_never_shifts_existing_items():
    """Reasons are keyed by index, so a restore must not move anything that
    is already there - even content that was originally first."""
    optimized = {"projects": [{"name": "Parser", "description": "A JSON parser"}]}
    original = {"projects": [{"name": "Old Game", "description": "A game"}, *optimized["projects"]]}
    [removed] = review.collect_changes(original, optimized, [])
    updated = review.apply_edits(optimized, {}, restores=[removed])
    assert [p["name"] for p in updated["projects"]] == ["Parser", "Old Game"]


def test_restoring_a_removed_bullet_returns_it_to_its_entry():
    optimized = {
        **ORIGINAL,
        "experience": [
            {"company": "Acme", "role": "Engineer", "details": [{"description": "Built APIs in Python"}]},
            ORIGINAL["experience"][1],
        ],
    }
    changes = review.collect_changes(ORIGINAL, optimized, [])
    removed = [c for c in changes if c["kind"] == review.REMOVED]
    assert [c["before"] for c in removed] == ["Ran on-call rotation", "Mentored two interns"]
    assert all(c["group"] == "Experience · Acme — Engineer" for c in removed)
    updated = review.apply_edits(optimized, {}, restores=removed)
    assert [d["description"] for d in updated["experience"][0]["details"]] == [
        "Built APIs in Python", "Ran on-call rotation", "Mentored two interns",
    ]


def test_restoring_a_whole_removed_entry():
    optimized = {**ORIGINAL, "experience": [ORIGINAL["experience"][0]]}
    [removed] = review.collect_changes(ORIGINAL, optimized, [])
    assert removed["id"] == "removed:experience.1"
    assert removed["group"] == "Experience · Globex — Intern"
    updated = review.apply_edits(optimized, {}, restores=[removed])
    assert updated["experience"][1]["company"] == "Globex"


def test_bullets_stored_as_plain_strings_still_work():
    original = {"experience": [{"company": "Acme", "role": "Eng", "details": ["Did a thing"]}]}
    optimized = {"experience": [{"company": "Acme", "role": "Eng", "details": ["Did a bigger thing"]}]}
    [change] = review.collect_changes(original, optimized, [])
    assert change["before"] == "Did a thing"
    updated = review.apply_edits(optimized, {change["path"]: "Did the biggest thing"})
    assert updated["experience"][0]["details"] == ["Did the biggest thing"]
