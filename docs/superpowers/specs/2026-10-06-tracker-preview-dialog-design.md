# Tracker: preview dialog, Prep/Radar removed

Date: 2026-10-06. Approved by the user in chat (option A).

## Goal

In the Tracker view, a saved application is one clean row. Clicking its
Preview button opens a dialog that compiles the saved resume JSON to PDF,
shows it inline, and offers PDF / Word downloads. All per-record editing
(notes, status, update, delete) lives in that dialog too. The Prep
(interview questions) and Radar (skill gap) features are removed entirely.

## Removed

- `Prep` / `Radar` buttons, their result panels and session keys
  (`prep_result_*`, `radar_result_*`) in `firebase_dashboard.render_dashboard`.
- `prep_interview_questions`, `prep_skill_gap` wrappers in `firebase_dashboard.py`.
- `ai.predict_interview_questions`, `ai.analyze_skill_gap` (no other callers).
- `View Data` / `Hide Data` inline panel and the `active_tracker_detail` key.
- The per-row `@st.fragment`: the row has no editable widgets any more.

`plotly` stays: the Performance Overview funnel still uses it.

## Row

One bordered container per record: company (bold) + target role caption,
status (coloured text) + applied date, and a `Preview` button (icon + label,
full width of its column, `key=f"preview_{stage}_{doc_id}"`).

## Dialog

`@st.dialog("Application", width="large")`, opened only from the Preview
button's `if st.button(...)` branch (Streamlit dialogs are fragments, so
widgets inside keep it open; an app-scope `st.rerun()` closes it).

Top to bottom:

1. Company heading, caption with role, status and every recorded date.
2. Template selectbox (Tech / Business, default Tech), `Download PDF`,
   `Download Word`.
3. pdf.js preview of the compiled resume (section order: all five default
   blocks). Compile runs under a spinner. Result is cached in
   `st.session_state.tracker_pdf_cache[(doc_id, template)]`, bounded to 8
   entries, and a failed compile (`None`) is never cached. If LuaLaTeX is
   missing the existing message is shown, the PDF button is hidden and the
   Word download remains.
4. Expander "Saved job description & resume JSON": JD text, Copy JSON
   button, `st.json`.
5. Notes text area, status selectbox, `Update`, `Delete`. Delete is
   two-step: first click shows a warning with `Yes, delete` / `Cancel`.
   Update and confirmed delete call the existing Firestore helpers then
   `st.rerun()`.

## Module boundary

`firebase_dashboard.py` must not import `app.py`. `render_dashboard` gains
three keyword callables supplied by `app.py`:

- `build_pdf(resume_json, template_label) -> bytes | None`
- `build_docx(resume_json) -> bytes | None`
- `render_pdf(pdf_bytes, height)`

Missing callables degrade to an info message, never an exception.

## Tests

`tests/test_tracker_preview.py` (AppTest, Firestore faked at
`firebase_dashboard.init_firebase`, `subprocess.run` faked like
`tests/test_profile_export.py`): row has Preview and no Prep/Radar/View
Data; Preview compiles once and shows PDF + Word downloads; reopening the
same record does not recompile; Delete needs confirmation; the removed AI
helpers no longer exist.
