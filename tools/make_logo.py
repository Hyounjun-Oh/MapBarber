"""Generate the MapBarber icon and README logos (SVG)."""
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C30 = math.cos(math.radians(30))
LEVEL_RGB = {1: (59, 108, 220), 2: (38, 196, 178), 3: (240, 200, 50)}
STRAY_RGB = (255, 40, 200)


def shade(rgb, factor):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * factor))) for c in rgb)


def cube(cx, cy, s, rgb, stroke="#11141a", width=1.6):
    top = [(cx, cy - s), (cx + s * C30, cy - s / 2), (cx, cy), (cx - s * C30, cy - s / 2)]
    left = [(cx - s * C30, cy - s / 2), (cx, cy), (cx, cy + s), (cx - s * C30, cy + s / 2)]
    right = [(cx, cy), (cx + s * C30, cy - s / 2), (cx + s * C30, cy + s / 2), (cx, cy + s)]
    out = []
    for face, factor in ((left, 0.78), (right, 0.58), (top, 1.12)):
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in face)
        out.append(f'<polygon points="{points}" fill="{shade(rgb, factor)}" stroke="{stroke}" stroke-width="{width}" '
                   'stroke-linejoin="round"/>')
    return out


def voxel_hill(ox, oy, s):
    heights = [[3, 2, 1], [2, 2, 1], [1, 1, 1]]
    shapes = []
    cells = [(i, j, k) for i in range(3) for j in range(3) for k in range(heights[i][j])]
    cells.sort(key=lambda c: (c[0] + c[1], c[2]))
    for i, j, k in cells:
        cx = ox + (j - i) * s * C30
        cy = oy + (i + j) * s / 2 - k * s
        shapes += cube(cx, cy, s, LEVEL_RGB[min(k + 1, 3)])
    return shapes


def scissors(x, y, angle, scale=1.0, opening=22):
    blade = "M -6 -5 L 66 -3.5 Q 75 0 66 3.5 L -6 5 Z"
    parts = [f'<g transform="translate({x:.1f},{y:.1f}) rotate({angle:.1f}) scale({scale:.2f})">']
    for sign in (1, -1):
        parts.append(f'<g transform="rotate({opening / 2 * sign})">')
        parts.append(f'<path d="{blade}" fill="#e9ecf2" stroke="#11141a" stroke-width="2.6" stroke-linejoin="round"/>')
        parts.append("</g>")
    for sign in (1, -1):
        parts.append(f'<g transform="rotate({-opening / 2 * sign})">')
        parts.append(f'<path d="M -3 0 L -24 {6 * sign}" stroke="#11141a" stroke-width="10" stroke-linecap="round"/>')
        parts.append(f'<path d="M -3 0 L -24 {6 * sign}" stroke="#e8504a" stroke-width="6" stroke-linecap="round"/>')
        parts.append(f'<circle cx="-34" cy="{10 * sign}" r="11" fill="none" stroke="#11141a" stroke-width="10"/>')
        parts.append(f'<circle cx="-34" cy="{10 * sign}" r="11" fill="none" stroke="#e8504a" stroke-width="6"/>')
        parts.append("</g>")
    parts.append('<circle cx="0" cy="0" r="4.5" fill="#11141a"/><circle cx="0" cy="0" r="2.2" fill="#e9ecf2"/>')
    parts.append("</g>")
    return parts


def icon_body():
    parts = ['<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
             '<stop offset="0" stop-color="#252a33"/><stop offset="1" stop-color="#14171c"/></linearGradient></defs>',
             '<rect x="4" y="4" width="248" height="248" rx="56" fill="url(#bg)"/>']
    parts += voxel_hill(96, 128, 28)
    pivot, angle, scale, opening = (206, 70), 152, 0.82, 40
    direction = (math.cos(math.radians(angle)), math.sin(math.radians(angle)))
    stray = (pivot[0] + direction[0] * 44, pivot[1] + direction[1] * 44)
    for dx, dy, size, turn in ((-22, 30, 6, 20), (-8, 42, 5, -15), (-30, 50, 4, 35)):
        parts.append(f'<rect x="{stray[0] + dx:.1f}" y="{stray[1] + dy:.1f}" width="{size}" height="{size}" rx="1" '
                     f'fill="{shade(STRAY_RGB, 0.9)}" transform="rotate({turn} {stray[0] + dx:.1f} {stray[1] + dy:.1f})"/>')
    parts += cube(stray[0], stray[1], 12, STRAY_RGB, width=1.4)
    parts += scissors(*pivot, angle, scale, opening)
    return parts


def write(path, width, height, body):
    with open(path, "w") as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n')
        f.write("\n".join(body))
        f.write("\n</svg>\n")
    print(path)


def logo(text_rgb, tagline_rgb):
    body = ['<g transform="translate(8,8) scale(0.72)">'] + icon_body() + ["</g>"]
    font = "font-family=\"'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif\""
    body.append(f'<text x="206" y="108" {font} font-size="72" font-weight="800" letter-spacing="-1.5">'
                f'<tspan fill="{text_rgb}">Map</tspan><tspan fill="#e8504a">Barber</tspan></text>')
    body.append(f'<text x="210" y="148" {font} font-size="22" font-weight="500" fill="{tagline_rgb}" '
                'letter-spacing="0.5">a barbershop for robot maps</text>')
    return body


if __name__ == "__main__":
    write(os.path.join(ROOT, "mapbarber", "assets", "icon.svg"), 256, 256, icon_body())
    write(os.path.join(ROOT, "docs", "logo-light.svg"), 640, 200, logo("#1d2129", "#5a6170"))
    write(os.path.join(ROOT, "docs", "logo-dark.svg"), 640, 200, logo("#f2f4f8", "#a3aab8"))
