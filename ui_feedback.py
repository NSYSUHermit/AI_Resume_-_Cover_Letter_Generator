import streamlit as st


def run_ai_call(label, fn, success=None):
    """Run a blocking AI call inside a native st.status panel.

    Returns whatever fn() returns, unchanged, so callers keep their existing
    result handling. Nothing global is mutated: an unsuccessful call leaves the
    page fully interactive instead of stranding the user behind a CSS overlay.

    success: optional predicate applied to the result to decide whether the
    status panel closes as complete or stays open as an error.
    """
    with st.status(label, expanded=True) as status:
        st.write("Contacting Gemini...")
        result = fn()
        ok = True if success is None else bool(success(result))
        status.update(
            label=f"{label} - done" if ok else f"{label} - failed",
            state="complete" if ok else "error",
            expanded=not ok,
        )
        return result
