"""Single source of truth for the colours used across the app.

The main stylesheet and the `components.html` buttons in app.py and
firebase_dashboard.py each used to hard-code the same hex values, so changing
the brand colour meant editing four places. Iframes cannot read the parent
page's CSS variables, so the Python dict is the only thing they can share.
"""

TOKENS = {
    "bg": "#f8fafc",
    "surface": "#ffffff",
    "surface-soft": "#f1f5f9",
    "border": "#e2e8f0",
    "border-strong": "#bfdbfe",
    "text": "#111827",
    "muted": "#64748b",
    "brand": "#2563eb",
    "brand-dark": "#1d4ed8",
    "success": "#059669",
    "warning": "#d97706",
    "danger": "#dc2626",
}

FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'


def css_root_block():
    """Render TOKENS as a CSS :root block, plus the non-colour design tokens."""
    variables = "\n".join(f"        --{name}: {value};" for name, value in TOKENS.items())
    return ":root {\n" + variables + """
        --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.06);
        --shadow-md: 0 10px 24px rgba(15, 23, 42, 0.08);
        --radius: 8px;
        --ease: 180ms ease-in-out;
    }"""


def walker_svg():
    """The little walking-figure SVG markup, in brand colour.

    Single source of truth for this asset, shared by app.py's
    render_floating_progress() (the top-centre floating progress bar, Task 1)
    and ui_feedback.run_ai_call() (the compact generation-status panel,
    Task 4) - both need the exact same figure, so it lives here once instead
    of being copy-pasted a second time. Only the markup is defined here; the
    walk-cycle animation itself (.gp-bob/.gp-legs/.gp-legs2 and their
    keyframes) lives in app.py's single stylesheet block, which both callers
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
