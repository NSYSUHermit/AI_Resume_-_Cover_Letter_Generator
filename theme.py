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
