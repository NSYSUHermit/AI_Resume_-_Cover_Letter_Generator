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
