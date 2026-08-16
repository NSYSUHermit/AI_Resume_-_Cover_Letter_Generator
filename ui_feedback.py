import html

import streamlit as st

from theme import walker_svg


def run_ai_call(label, fn, success=None, target=None):
    """Run a blocking AI call, reporting real milestones as it goes.

    `fn` is called with a single `report` argument. Calling report("...") writes
    the current milestone into view, so the user watches real stages land
    instead of a timer pretending to be progress - the docstring this replaces
    said the same thing, and that is still exactly the contract: message
    *content* is untouched, only the visual presentation changed (Task 4, and
    again in the visual-polish follow-up described below).

    `target`, when given, is an existing `st.empty()` placeholder - typically
    one a caller already drew its own button into - that the in-flight state
    is rendered into *instead of* the st.status panel described below. Owner:
    「optimizing resume 的動畫就跑在同一顆按鈕上就好不要額外延展」(the animation
    should just run on the same button, no extra expansion). Streamlit 1.61.1
    gives st.button() no way to swap its own label for streaming text - a
    button is a fixed widget, not a placeholder - so this instead overwrites
    the placeholder the caller's button was drawn into: the button disappears
    and a same-row, same-width "spinner + latest milestone" line (.gp-btn-status,
    styled to match the primary-button footprint in app.py's stylesheet) takes
    its place, using the exact same report()-driven stream as the panel below,
    just aimed at a different element. Nothing new is inserted into the layout
    - the button's own row *is* the status row - which is what "不要額外延展"
    (no extra expansion) requires. streamlit==1.61.1's st.status() does gain a
    `type="compact"` option, but inspecting streamlit/elements/layouts.py's
    own docstring shows it is still "a minimal inline toggle" - a distinct
    block-level element in its own right, rendered wherever that call site
    sits, not layered onto an existing widget - so it does not reach "on the
    button" either; confirmed by reading the installed package, not assumed.
    On failure (no rerun follows - see below), the frozen line stays put same
    as the st.status branch does; it is the call site's job to redraw its own
    button into `target` afterward if it wants the row clickable again before
    the next natural rerun (render_generator_workspace()'s Optimize Resume
    button does this). Every other call site leaves `target` as None and gets
    the unchanged st.status panel - confirmed by
    tests/test_ui_feedback.py's existing coverage of that path, which this
    parameter does not touch.

    Compact panel, not a growing log: only the most recent report() message is
    ever on screen, with a walking-figure SVG marching in place beside it -
    design doc: "面板改為緊湊樣式，左側放與懸浮 bar 同一個小人 SVG，做原地踏步動畫，
    右側是最新的里程碑文字". theme.walker_svg() is the one place that SVG is
    defined, so this is not a second copy of it, and the walk-cycle keyframes
    it relies on (.gp-bob/.gp-legs/.gp-legs2) live once in app.py's
    stylesheet, which is injected unconditionally before any view-specific
    rendering can reach this function - true for every call site of
    run_ai_call, in both app.py and firebase_dashboard.py. The walker only
    marches in place here (no `left` position to drive): a single blocking
    call has no meaningful horizontal "progress" of its own.

    This panel is theme.walker_svg()'s only remaining caller: it originally
    shared the figure with app.py's top-centre floating progress bar
    (render_floating_progress()), but the visual-polish pass that replaced
    that bar with a hairline top status strip (render_progress_strip())
    dropped the figure rather than shrinking it to fit - see that function's
    own docstring, and theme.walker_svg()'s.

    Returns whatever fn() returns, unchanged. Nothing global is mutated, so an
    unsuccessful call leaves the page fully interactive rather than stranding
    the user behind a CSS overlay.

    Note this panel is torn down by the rerun that usually follows a successful
    call. Lasting confirmation is the result banner's job, not this panel's.
    On failure there is no rerun, so the panel (and whatever it last showed)
    stays on screen indefinitely - the walker is frozen out of the final
    message once fn() returns (see `last_message` below) so a failed call
    does not read as "still working" forever. Success never shows this: the
    caller's own st.rerun() a moment later replaces the whole panel anyway.
    """
    walker = walker_svg()
    last_message = [None]

    if target is not None:
        # On-the-button path (see docstring). Same escaping rule as the panel
        # branch below - report() can carry AI-echoed job-description text -
        # and the same freeze-on-exit rule: once fn() returns, redraw without
        # the walker so a resolved call never reads as "still working".
        def render_line(text, walking):
            marker = walker if walking else ""
            target.markdown(
                f'<div class="gp-btn-status">{marker}<span>{html.escape(text)}</span></div>',
                unsafe_allow_html=True,
            )

        render_line(label, True)

        def report(message):
            last_message[0] = message
            render_line(message, True)

        result = fn(report)
        ok = True if success is None else bool(success(result))
        render_line(last_message[0] if last_message[0] is not None else label, False)
        return result

    # Keyed container so app.py's stylesheet can mark "in progress" in brand
    # blue, paired with the green result banner that reports the outcome.
    with st.container(key="ai_status"), st.status(label, expanded=True) as status:
        line = st.empty()

        def report(message):
            last_message[0] = message
            # html.escape(): message can carry AI-echoed job-description text
            # (e.g. ai_optimize_and_update()'s "Target: ..." line includes the
            # screening model's target_company/target_role, both read out of
            # whatever JD the user pasted in). st.write(message) (what this
            # replaces) ran every message through markdown's own escaping;
            # this now goes through unsafe_allow_html=True instead, so the
            # dynamic part needs its own escaping to keep a literal "<"/"&" in
            # a company name from being interpreted as markup - the walker/div
            # wrapper around it is ours, not user data, and stays unescaped.
            line.markdown(
                f'<div class="gp-status-line">{walker}<span>{html.escape(message)}</span></div>',
                unsafe_allow_html=True,
            )

        result = fn(report)
        ok = True if success is None else bool(success(result))
        if last_message[0] is not None:
            line.markdown(
                f'<div class="gp-status-line"><span>{html.escape(last_message[0])}</span></div>',
                unsafe_allow_html=True,
            )
        status.update(
            label=f"{label} — done" if ok else f"{label} — failed",
            state="complete" if ok else "error",
            expanded=not ok,
        )
        return result
