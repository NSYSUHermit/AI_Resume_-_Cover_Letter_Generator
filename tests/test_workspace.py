import workspace


def test_new_user_lands_on_profile():
    assert workspace.initial_view(resume_is_empty=True) == workspace.PROFILE


def test_returning_user_lands_on_generator():
    assert workspace.initial_view(resume_is_empty=False) == workspace.GENERATOR


def test_views_are_exactly_three_in_order():
    assert [view for view, _, _ in workspace.VIEWS] == [
        workspace.PROFILE,
        workspace.GENERATOR,
        workspace.TRACKER,
    ]


def test_progress_starts_all_incomplete():
    steps = workspace.application_progress(
        jd_text="", has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert [done for _, done in steps] == [False, False, False, False]


def test_short_jd_does_not_count_as_added():
    steps = workspace.application_progress(
        jd_text="too short", has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert steps[0][1] is False


def test_long_jd_counts_as_added():
    steps = workspace.application_progress(
        jd_text="x" * 51, has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert steps[0][1] is True


def test_missing_jd_is_treated_as_empty():
    steps = workspace.application_progress(
        jd_text=None, has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert steps[0][1] is False


def test_progress_labels_are_in_application_order():
    steps = workspace.application_progress(
        jd_text="", has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert [label for label, _ in steps] == [
        "Job description added",
        "Resume optimized",
        "PDF generated",
        "Saved to tracker",
    ]


def test_all_four_stages_can_be_complete():
    steps = workspace.application_progress(
        jd_text="x" * 51, has_optimized=True, has_pdf=True, is_tracked=True
    )
    assert all(done for _, done in steps)


def test_logged_out_user_never_records():
    assert workspace.should_record_application(is_tracked=False, logged_in=False) is False


def test_first_download_records():
    assert workspace.should_record_application(is_tracked=False, logged_in=True) is True


def test_second_download_does_not_record_again():
    assert workspace.should_record_application(is_tracked=True, logged_in=True) is False


def test_logged_out_user_with_stale_flag_still_does_not_record():
    assert workspace.should_record_application(is_tracked=True, logged_in=False) is False


def test_recent_applications_empty_when_no_records():
    assert workspace.recent_applications([]) == []
    assert workspace.recent_applications(None) == []


def test_recent_applications_caps_at_the_limit():
    records = [{"company_name": f"Co{i}", "status": "Applied"} for i in range(5)]
    assert len(workspace.recent_applications(records)) == 3
    assert len(workspace.recent_applications(records, limit=2)) == 2


def test_recent_applications_preserves_caller_order():
    """Newest-first is the caller's job (the Firestore query itself orders by
    applied_date descending) - this only takes a prefix, it must not re-sort."""
    records = [
        {"company_name": "Newest", "status": "Applied"},
        {"company_name": "Middle", "status": "Applied"},
        {"company_name": "Oldest", "status": "Applied"},
    ]
    rows = workspace.recent_applications(records)
    assert [r["company"] for r in rows] == ["Newest", "Middle", "Oldest"]


def test_recent_applications_reads_role_from_nested_resume_json():
    records = [{
        "company_name": "Acme",
        "status": "Applied",
        "resume_json": {"target_role": "Backend Engineer"},
    }]
    rows = workspace.recent_applications(records)
    assert rows[0] == {"company": "Acme", "role": "Backend Engineer", "status_dot_token": "brand"}


def test_recent_applications_falls_back_like_render_dashboard_does():
    """Same "Unknown" default firebase_dashboard.render_dashboard() already
    uses for a missing company_name; role has no fallback string of its own
    (it just comes back "") since there is no single-word placeholder that
    reads as real data rather than a fabricated one."""
    rows = workspace.recent_applications([{}])
    assert rows[0]["company"] == "Unknown"
    assert rows[0]["role"] == ""


def test_recent_applications_status_dot_tokens():
    records = [
        {"company_name": "A", "status": "Applied"},
        {"company_name": "B", "status": "Interviewing"},
        {"company_name": "C", "status": "Offered"},
    ]
    tokens = [r["status_dot_token"] for r in workspace.recent_applications(records, limit=3)]
    assert tokens == ["brand", "warning", "success"]

    rejected = workspace.recent_applications([{"company_name": "D", "status": "Rejected"}])
    assert rejected[0]["status_dot_token"] == "danger"

    unknown_status = workspace.recent_applications([{"company_name": "E", "status": "Withdrawn"}])
    assert unknown_status[0]["status_dot_token"] == "muted"

    missing_status = workspace.recent_applications([{"company_name": "F", "status": None}])
    assert missing_status[0]["status_dot_token"] == "brand"  # missing status defaults to "Applied"
