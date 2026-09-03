"""Composite live LCD content onto the rendered device screen, in perspective.

The screen is a tilted disc in world space. We build the same camera used by
raster.py, project four corners of a square inscribed in that disc, then warp a
flat text panel onto the resulting quad.
"""
import math, numpy as np
from PIL import Image, ImageDraw, ImageFont

# must match make_color.py / raster.py
HEAD_HALF_D, SCREEN_R, HEAD_Z, TILT_DEG = 10.0, 19.0, 55.0, 12.0
W, H = 1200, 1000
AZ, EL, DIST = 145.0, 14.0, 250.0
TARGET = np.array([0, 0, 46], dtype=float)
FOCAL = 2.9 * min(W, H) / 2


def project(pts):
    a, e = math.radians(AZ), math.radians(EL)
    v = np.asarray(pts, dtype=float) - TARGET
    ca, sa = math.cos(a), math.sin(a)
    x = v[:, 0]*ca + v[:, 1]*sa
    y = -v[:, 0]*sa + v[:, 1]*ca
    z = v[:, 2]
    ce, se = math.cos(e), math.sin(e)
    cy, cz = y*ce + z*se, -y*se + z*ce
    depth = cy + DIST
    return np.stack([x*FOCAL/depth + W/2, -cz*FOCAL/depth + H/2], axis=1)


def screen_quad(inset=1.0):
    """Four corners of a square on the screen plane, in world coords."""
    a = math.radians(-(90.0 - TILT_DEG))
    ca, sa = math.cos(a), math.sin(a)
    U = np.array([-1.0, 0.0, 0.0])                # screen right (camera is at az 145)
    Vup = np.array([0.0, -ca, -sa])               # screen up
    Zw = np.array([0.0, -sa, ca])                 # screen outward normal
    C = np.array([0.0, 0.0, HEAD_Z]) + Zw * (HEAD_HALF_D - 0.35)
    s = SCREEN_R * inset
    return np.array([C - s*U + s*Vup,             # top-left
                     C + s*U + s*Vup,             # top-right
                     C + s*U - s*Vup,             # bottom-right
                     C - s*U - s*Vup])            # bottom-left


def screen_circle(n=64, inset=0.985):
    """Points around the screen disc, world coords - used as the composite mask."""
    a = math.radians(-(90.0 - TILT_DEG))
    ca, sa = math.cos(a), math.sin(a)
    U = np.array([-1.0, 0.0, 0.0]); Vup = np.array([0.0, -ca, -sa])
    Zw = np.array([0.0, -sa, ca])
    C = np.array([0.0, 0.0, HEAD_Z]) + Zw * (HEAD_HALF_D - 0.35)
    r = SCREEN_R * inset
    return np.array([C + r*math.cos(t)*U + r*math.sin(t)*Vup
                     for t in np.linspace(0, 2*math.pi, n, endpoint=False)])


def coeffs(dest, src):
    m = []
    for (dx, dy), (sx, sy) in zip(dest, src):
        m.append([dx, dy, 1, 0, 0, 0, -sx*dx, -sx*dy])
        m.append([0, 0, 0, dx, dy, 1, -sy*dx, -sy*dy])
    A = np.array(m, dtype=float)
    B = np.array(src, dtype=float).reshape(8)
    return np.linalg.solve(A, B)


def font(sz, bold=False):
    for n in (("arialbd.ttf" if bold else "arial.ttf"), "consola.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(n, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def panel(state, project_name, detail, accent, bg, muted, px=760):
    """Flat LCD content, drawn square then warped."""
    im = Image.new("RGBA", (px, px), bg + (255,))
    d = ImageDraw.Draw(im)
    cx = px // 2

    d.text((cx, int(px*0.30)), state.upper(), font=font(int(px*0.062), True),
           fill=accent + (255,), anchor="mm")
    d.text((cx, int(px*0.465)), project_name, font=font(int(px*0.108), True),
           fill=(238, 241, 245, 255), anchor="mm")
    d.text((cx, int(px*0.605)), detail, font=font(int(px*0.046)),
           fill=muted + (255,), anchor="mm")

    # a row of session pips, so the screen reads as live UI
    n, r, gap = 4, int(px*0.010), int(px*0.040)
    x0 = cx - (n - 1) * gap // 2
    for i in range(n):
        col = accent + (255,) if i == 0 else (95, 105, 120, 255)
        d.ellipse([x0 + i*gap - r, int(px*0.695) - r,
                   x0 + i*gap + r, int(px*0.695) + r], fill=col)
    return im


def apply(render_path, out_path, state, name, detail, accent, bg, muted):
    base = Image.open(render_path).convert("RGBA")
    quad = project(screen_quad())
    src = panel(state, name, detail, accent, bg, muted)
    w, h = src.size
    c = coeffs([tuple(p) for p in quad], [(0, 0), (w, 0), (w, h), (0, h)])
    warped = src.transform((W, H), Image.PERSPECTIVE, c, Image.BICUBIC)

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in project(screen_circle())], fill=255)
    base.alpha_composite(Image.composite(warped, Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask))
    base.convert("RGB").save(out_path)
    print(out_path)


if __name__ == "__main__":
    apply("Vigil-graphite-product.png", "Vigil-graphite-screen.png",
          "blocked", "your-project", "needs permission  ·  14m",
          accent=(255, 140, 66), bg=(8, 13, 10), muted=(150, 160, 175))
    apply("Vigil-white-product.png", "Vigil-white-screen.png",
          "working", "your-project", "running tests  ·  7m",
          accent=(38, 110, 235), bg=(233, 238, 245), muted=(105, 118, 135))
