"""Tiny SVG helpers for the README diagrams (shared visual style across projects)."""

from html import escape

FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
INK, MUTED, BODY = "#0F172A", "#475569", "#334155"
PALETTE = {
    "blue": ("#EFF6FF", "#BFDBFE", "#2563EB", "#1D4ED8"),
    "violet": ("#F5F3FF", "#DDD6FE", "#7C3AED", "#6D28D9"),
    "teal": ("#F0FDFA", "#99F6E4", "#0F766E", "#0F766E"),
    "amber": ("#FFFBEB", "#FDE68A", "#D97706", "#B45309"),
    "green": ("#F0FDF4", "#BBF7D0", "#16A34A", "#15803D"),
    "purple": ("#FAF5FF", "#E9D5FF", "#6E56CF", "#6E56CF"),
    "slate": ("#F8FAFC", "#E2E8F0", "#94A3B8", "#334155"),
}


def t(x, y, s, size=12, fill=BODY, weight=None, anchor=None, extra=""):
    w = f' font-weight="{weight}"' if weight else ""
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}"{w}{a}{extra}>{escape(s)}</text>'


def lines(x, y, rows, size=12, fill=BODY, gap=20, anchor=None, weight=None):
    return "\n".join(t(x, y + i * gap, r, size, fill, weight, anchor) for i, r in enumerate(rows))


def svg(w, h, title, subtitle, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'font-family="{FONT}">\n<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
            f'fill="{MUTED}"/></marker></defs>\n<rect width="{w}" height="{h}" fill="#FFFFFF"/>\n'
            + t(40, 52, title, 28, INK, 700) + "\n" + t(40, 80, subtitle, 15, MUTED) + "\n" + body + "\n</svg>\n")


def lane(x, y, w, h, color, label):
    bg, border, _, dark = PALETTE[color]
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{bg}" stroke="{border}"/>\n'
            + t(x + 20, y + 28, label, 13, dark, 700, extra=' letter-spacing="1"'))


def box(x, y, w, h, color, title, rows, plain=False):
    _, _, stroke, dark = PALETTE[color]
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#FFFFFF" '
           f'stroke="{"#94A3B8" if plain else stroke}" stroke-width="{1 if plain else 2}"/>',
           t(x + 18, y + 30, title, 15, INK if plain else dark, 700), lines(x + 18, y + 56, rows, 12, BODY, 20)]
    return "\n".join(out)


def arrow(x1, y1, x2, y2):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{MUTED}" stroke-width="2" marker-end="url(#arrow)"/>'


def card(x, y, w, h, color, big, head, rows, big_size=34):
    bg, border, _, dark = PALETTE[color]
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{bg}" stroke="{border}"/>\n'
            + t(x + 20, y + 46, big, big_size, dark, 800) + "\n" + t(x + 20, y + 76, head, 14, INK, 700) + "\n"
            + lines(x + 20, y + 100, rows, 12, MUTED, 18))


def panel(x, y, w, h, title, subtitle=None):
    out = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="#F8FAFC" stroke="#E2E8F0"/>\n'
           + t(x + 20, y + 32, title, 16, INK, 700))
    return out + ("\n" + t(x + 20, y + 54, subtitle, 12, "#64748B") if subtitle else "")


def hbar(x, y, label, value, vmax, width, color, text, label_w=190, bold=False):
    bw = max(2, width * value / vmax)
    out = [t(x + label_w - 12, y + 19, label, 13, INK if bold else BODY, 700 if bold else None, "end"),
           f'<rect x="{x + label_w}" y="{y}" width="{width}" height="28" rx="4" fill="#F1F5F9"/>',
           f'<rect x="{x + label_w}" y="{y}" width="{bw:.1f}" height="28" rx="4" fill="{color}"/>']
    if bw > 70:
        out.append(t(x + label_w + bw - 10, y + 19, text, 13, "#FFFFFF", 700, "end"))
    else:
        out.append(t(x + label_w + bw + 8, y + 19, text, 13, BODY, 700))
    return "\n".join(out)
