"""Software rasteriser with a real z-buffer, so parts occlude correctly.
Renders the Vigil concept as a presentation image, halo lit."""
import struct, math, numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont

W, H, SS = 1200, 1000, 2          # SS = supersample factor
PARTS = ["shell", "knurl", "diffuser", "screen", "button", "pad"]
EMISSIVE = {"diffuser", "button"}

CW = {
 "graphite": dict(shell="#3A4048", knurl="#20242A", diffuser="#FF8C42",
                  screen="#080D0A", button="#FF8C42", pad="#141719",
                  bg="#0E1116", floor="#161A20"),
 "white":    dict(shell="#F3F5F7", knurl="#C9CED5", diffuser="#4C8DFF",
                  screen="#E9EEF5", button="#4C8DFF", pad="#2A2F36",
                  bg="#0E1116", floor="#181C22"),
}

def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i+2], 16)/255 for i in (0, 2, 4)], dtype=np.float32)

def load(p):
    with open(p, "rb") as f:
        f.read(80); n = struct.unpack("<I", f.read(4))[0]
        t = np.empty((n, 3, 3), dtype=np.float32)
        for i in range(n):
            f.read(12)
            t[i] = np.frombuffer(f.read(36), dtype="<f4").reshape(3, 3)
            f.read(2)
    return t

def look_at(tris, az, el, dist, target):
    """World -> camera space."""
    a, e = math.radians(az), math.radians(el)
    v = tris.reshape(-1, 3) - target
    ca, sa = math.cos(a), math.sin(a)
    x = v[:, 0]*ca + v[:, 1]*sa
    y = -v[:, 0]*sa + v[:, 1]*ca
    z = v[:, 2]
    ce, se = math.cos(e), math.sin(e)
    y2 = y*ce + z*se
    z2 = -y*se + z*ce
    out = np.stack([x, z2, y2 + dist], axis=1)   # x right, y up, z forward
    return out.reshape(-1, 3, 3)

def render(cw):
    cols = CW[cw]
    w, h = W*SS, H*SS
    zbuf = np.full((h, w), 1e9, dtype=np.float32)
    img = np.zeros((h, w, 3), dtype=np.float32)
    emis = np.zeros((h, w), dtype=np.float32)
    img[:, :] = hexrgb(cols["bg"])

    light = np.array([-0.42, 0.72, -0.55], dtype=np.float32)
    light /= np.linalg.norm(light)
    fill = np.array([0.55, 0.25, -0.75], dtype=np.float32)
    fill /= np.linalg.norm(fill)

    target = np.array([0, 0, 46], dtype=np.float32)
    focal = 2.9*SS*min(W, H)/2

    for name in PARTS:
        tris = load(f"parts/Vigil-{name}.stl")
        cam = look_at(tris, az=145, el=14, dist=250, target=target)

        n = np.cross(cam[:, 1]-cam[:, 0], cam[:, 2]-cam[:, 0])
        n /= (np.linalg.norm(n, axis=1, keepdims=True) + 1e-9)

        base = hexrgb(cols[name])
        lam = np.clip(n @ light, 0, 1)
        lam2 = np.clip(n @ fill, 0, 1)
        view = np.array([0, 0, -1], dtype=np.float32)
        halfv = (light + view); halfv /= np.linalg.norm(halfv)
        spec = np.clip(n @ halfv, 0, 1)**36

        if name in EMISSIVE:
            shade = 0.90 + 0.10*lam
            col = np.clip(base[None, :]*shade[:, None] + 0.10, 0, 1)
        else:
            gloss = 0.55 if name in ("screen", "knurl", "pad") else 0.30
            shade = 0.24 + 0.74*lam + 0.22*lam2
            col = np.clip(base[None, :]*shade[:, None] + spec[:, None]*gloss, 0, 1)

        # project
        z = cam[:, :, 2]
        px = cam[:, :, 0]*focal/z + w/2
        py = -cam[:, :, 1]*focal/z + h/2

        for i in range(len(cam)):
            if z[i].min() < 1: continue
            x0, x1 = px[i].min(), px[i].max()
            y0, y1 = py[i].min(), py[i].max()
            ix0, ix1 = max(int(x0), 0), min(int(x1)+2, w)
            iy0, iy1 = max(int(y0), 0), min(int(y1)+2, h)
            if ix0 >= ix1 or iy0 >= iy1: continue
            ax, ay = px[i, 0], py[i, 0]
            bx, by = px[i, 1], py[i, 1]
            cx, cy = px[i, 2], py[i, 2]
            den = (by-cy)*(ax-cx) + (cx-bx)*(ay-cy)
            if abs(den) < 1e-9: continue
            X, Y = np.meshgrid(np.arange(ix0, ix1)+0.5, np.arange(iy0, iy1)+0.5)
            l1 = ((by-cy)*(X-cx) + (cx-bx)*(Y-cy))/den
            l2 = ((cy-ay)*(X-cx) + (ax-cx)*(Y-cy))/den
            l3 = 1-l1-l2
            m = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
            if not m.any(): continue
            zz = l1*z[i, 0] + l2*z[i, 1] + l3*z[i, 2]
            sub = zbuf[iy0:iy1, ix0:ix1]
            hit = m & (zz < sub)
            if not hit.any(): continue
            sub[hit] = zz[hit]
            img[iy0:iy1, ix0:ix1][hit] = col[i]
            if name in EMISSIVE:
                emis[iy0:iy1, ix0:ix1][hit] = 1.0

    # bloom from the emissive parts
    im = Image.fromarray((np.clip(img, 0, 1)*255).astype(np.uint8))
    gl = Image.fromarray((emis*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(26*SS))
    glow = np.asarray(gl, dtype=np.float32)[:, :, None]/255.0
    tint = hexrgb(cols["diffuser"])[None, None, :]
    out = np.clip(np.asarray(im, dtype=np.float32)/255.0 + glow*tint*0.68, 0, 1)

    im = Image.fromarray((out*255).astype(np.uint8)).resize((W, H), Image.LANCZOS)
    im.save(f"Vigil-{cw}-product.png")
    print(f"Vigil-{cw}-product.png")

for cw in CW:
    render(cw)
