import streamlit as st


def run_ai_call(label, fn, success=None):
    """Run a blocking AI call inside a native st.status panel.

    `fn` is called with a single `report` argument. Calling report("...") writes
    a line into the panel, so the user watches real milestones land instead of a
    timer pretending to be progress.

    Returns whatever fn() returns, unchanged. Nothing global is mutated, so an
    unsuccessful call leaves the page fully interactive rather than stranding
    the user behind a CSS overlay.

    Note this panel is torn down by the rerun that usually follows a successful
    call. Lasting confirmation is the result banner's job, not this panel's.
    """
    # Keyed container so app.py's stylesheet can mark "in progress" in brand
    # blue, paired with the green result banner that reports the outcome.
    with st.container(key="ai_status"), st.status(label, expanded=True) as status:
        def report(message):
            st.write(message)

        result = fn(report)
        ok = True if success is None else bool(success(result))
        status.update(
            label=f"{label} — done" if ok else f"{label} — failed",
            state="complete" if ok else "error",
            expanded=not ok,
        )
        return result
