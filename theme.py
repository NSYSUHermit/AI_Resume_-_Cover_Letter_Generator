"""Single source of truth for the colours used across the app.

The main stylesheet and the `components.html` buttons in app.py and
firebase_dashboard.py each used to hard-code the same hex values, so changing
the brand colour meant editing four places. Iframes cannot read the parent
page's CSS variables, so the Python dict is the only thing they can share.
"""

TOKENS = {
    # Restrained monochrome palette (zinc), one accent. Redesign of 2026-11:
    # Vercel / Apple-style engineering look - near-white ground, white
    # surfaces, 1px low-contrast hairlines, ink text, and the single blue
    # accent kept for the one core CTA (Optimize resume, Save key) and the
    # one key number (the ATS score). Everything else is ink or grey.
    "bg": "#fafafa",
    "surface": "#ffffff",
    "surface-soft": "#f4f4f5",
    # Hairline dividers and card edges (~7% ink on white).
    "border": "#ececee",
    "border-strong": "#d4d4d8",
    # Resting edge of text inputs, the chat box and other fields - one step
    # darker than --border so a field is visible on a white card. Also the
    # value of theme.borderColor in .streamlit/config.toml - keep in sync.
    "border-input": "#e4e4e7",
    "text": "#09090b",
    # Field labels and secondary copy that must stay readable (zinc-600).
    "text-2": "#52525b",
    # Small muted copy. zinc-500, not the lighter zinc-400 the design brief
    # suggested: 400 is ~2.6:1 on white and fails for small text; 500 is 4.8:1.
    "muted": "#71717a",
    "brand": "#2563eb",
    "brand-dark": "#1d4ed8",
    "success": "#059669",
    "warning": "#d97706",
    "danger": "#dc2626",
    # Ink: primary buttons, the active nav item, progress. Replaced the old
    # "navy" pair; a hover needs somewhere to go, so it lightens slightly.
    "ink": "#09090b",
    "ink-hover": "#27272a",
}

# Geist is loaded by .streamlit/config.toml ([theme] font / codeFont), which
# covers the main page. Iframes (components.html buttons, the pdf.js viewer)
# cannot see it and fall back to the system stack after it.
FONT_STACK = '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
FONT_MONO = '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'


def css_root_block():
    """Render TOKENS as a CSS :root block, plus the non-colour design tokens."""
    variables = "\n".join(f"        --{name}: {value};" for name, value in TOKENS.items())
    return ":root {\n" + variables + f"""
        --shadow-sm: 0 1px 1px rgba(9, 9, 11, 0.03);
        --shadow-md: 0 1px 2px rgba(9, 9, 11, 0.05);
        --radius: 6px;
        --radius-card: 12px;
        --ease: 160ms ease-in-out;
        --font-mono: {FONT_MONO};
    }}"""


def walker_svg():
    """The little walking-figure SVG markup, in brand colour.

    Single source of truth for this asset. Historically shared by two
    callers - app.py's old top-centre floating progress *pill* (Task 1) and
    ui_feedback.run_ai_call()'s compact generation-status panel (Task 4) -
    but the visual-polish pass that replaced the pill with a hairline top
    status strip (app.py's render_progress_strip()) dropped the figure
    rather than shrinking it into that much thinner strip, per that task's
    own instruction ("keep the walking figure only if it still fits ...
    drop the figure rather than fattening the strip"). ui_feedback.
    run_ai_call() is therefore this function's only remaining caller today;
    it still lives here (rather than moving into ui_feedback.py) because it
    is a visual asset keyed to TOKENS["brand"], the same reason every other
    colour-bearing asset in this module is defined next to TOKENS rather
    than next to its one caller. Only the markup is defined here; the
    walk-cycle animation itself (.gp-bob/.gp-legs/.gp-legs2 and their
    keyframes) lives in app.py's single stylesheet block, which the caller
    can rely on being present - it is injected unconditionally, before any
    view-specific rendering, on every script run.
    """
    brand = TOKENS["brand"]
    return f"""<svg class="gp-walker" viewBox="0 0 20 24" fill="none">
  <g class="gp-bob">
    <circle cx="10" cy="4.5" r="3.2" fill="{brand}"/>
    <path d="M10 8v7" stroke="{brand}" stroke-width="2.4" stroke-linecap="round"/>
    <g class="gp-legs">
      <path d="M10 15l-3.5 5M10 15l3.5 5" stroke="{brand}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M10 10l-4 2.5M10 10l4 2" stroke="{brand}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="gp-legs2">
      <path d="M10 15l-1.5 5.5M10 15l4.5 4" stroke="{brand}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M10 10l-4 1.5M10 10l3.5 3" stroke="{brand}" stroke-width="2" stroke-linecap="round"/>
    </g>
  </g>
</svg>"""
