import html

import streamlit as st

from theme import walker_svg


def run_ai_call(label, fn, success=None):
    """Run a blocking AI call inside a native st.status panel.

    `fn` is called with a single `report` argument. Calling report("...") writes
    the current milestone into the panel, so the user watches real stages land
    instead of a timer pretending to be progress - the docstring this replaces
    said the same thing, and that is still exactly the contract: message
    *content* is untouched, only the visual presentation changed (Task 4).

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
