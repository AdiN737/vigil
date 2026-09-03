"""
Vigil concept -> coloured 3MF + per-part STLs + presentation render.

STL carries no colour, so the model is built as SEPARATE BODIES:
  shell / knurl / diffuser / screen / button / pad
Each body is written as its own STL (assign a filament per file in your slicer)
and all of them are packed into a .3mf with real colours baked in.

Two colourways: graphite and white. Geometry is identical; only colour differs.
All dimensions mm.
"""
import math, struct, zipfile, os

# ----------------------------- parameters -----------------------------
SEG = 260

HEAD_R = 38.0
HEAD_HALF_D = 10.0
RIM_R = 4.0
SCREEN_R = 19.0
SCREEN_DEPTH = 3.0
HALO_IN = 25.0
HALO_OUT = 31.0
HALO_DEPTH = 3.4

HEAD_Z = 55.0
TILT_DEG = 12.0

NECK_R_BOT, NECK_R_TOP = 27.0, 19.0
NECK_Z0, NECK_Z1 = 11.0, 27.0

BASE_R, BASE_H, BASE_FILLET = 43.0, 16.0, 6.0

BTN_R, BTN_OUT, BTN_ANGLE = 4.2, 7.5, 232.0

KNURL_TEETH = 56
KNURL_AMP = 0.45

# ----------------------------- helpers -----------------------------
def arc(cx, cz, r, a0, a1, n=16):
    return [(cx + r*math.cos(math.radians(a0+(a1-a0)*i/n)),
             cz + r*math.sin(math.radians(a0+(a1-a0)*i/n))) for i in range(n+1)]

def revolve(profile, seg=SEG):
    """Profile touching the axis at both ends -> closed solid."""
    tris = []
    for i in range(seg):
        a0, a1 = 2*math.pi*i/seg, 2*math.pi*(i+1)/seg
        c0, s0, c1, s1 = math.cos(a0), math.sin(a0), math.cos(a1), math.sin(a1)
        for j in range(len(profile)-1):
            r0, z0 = profile[j]; r1, z1 = profile[j+1]
            p00 = (r0*c0, r0*s0, z0); p01 = (r0*c1, r0*s1, z0)
            p10 = (r1*c0, r1*s0, z1); p11 = (r1*c1, r1*s1, z1)
            if r0 < 1e-9 and r1 < 1e-9: continue
            if r0 < 1e-9:   tris.append((p00, p10, p11))
            elif r1 < 1e-9: tris.append((p00, p01, p10))
            else:           tris += [(p00, p10, p11), (p00, p11, p01)]
    return tris

def revolve_loop(loop, seg=SEG, radial=None):
    """Closed (r,z) loop away from the axis -> tube/annulus solid.
    radial(theta) optionally scales r, for knurling."""
    tris = []
    n = len(loop)
    for i in range(seg):
        a0, a1 = 2*math.pi*i/seg, 2*math.pi*(i+1)/seg
        d0 = radial(a0) if radial else 0.0
        d1 = radial(a1) if radial else 0.0
        c0, s0, c1, s1 = math.cos(a0), math.sin(a0), math.cos(a1), math.sin(a1)
        for j in range(n):
            r0, z0 = loop[j]; r1, z1 = loop[(j+1) % n]
            A = ((r0+d0)*c0, (r0+d0)*s0, z0); B = ((r0+d1)*c1, (r0+d1)*s1, z0)
            C = ((r1+d0)*c0, (r1+d0)*s0, z1); D = ((r1+d1)*c1, (r1+d1)*s1, z1)
            tris += [(A, C, D), (A, D, B)]
    return tris

def rot_x(t, d):
    a=math.radians(d); c,s=math.cos(a),math.sin(a)
    return [tuple((x, y*c-z*s, y*s+z*c) for (x,y,z) in tri) for tri in t]
def rot_y(t, d):
    a=math.radians(d); c,s=math.cos(a),math.sin(a)
    return [tuple((x*c+z*s, y, -x*s+z*c) for (x,y,z) in tri) for tri in t]
def rot_z(t, d):
    a=math.radians(d); c,s=math.cos(a),math.sin(a)
    return [tuple((x*c-y*s, x*s+y*c, z) for (x,y,z) in tri) for tri in t]
def move(t, dx, dy, dz):
    return [tuple((x+dx, y+dy, z+dz) for (x,y,z) in tri) for tri in t]

def head_place(t):
    return move(rot_x(t, -(90.0-TILT_DEG)), 0, 0, HEAD_Z)

# ----------------------------- bodies -----------------------------
# 1. shell: puck (with groove + screen recess left as voids), neck, base
shell_p = [(0.0, HEAD_HALF_D-SCREEN_DEPTH), (SCREEN_R, HEAD_HALF_D-SCREEN_DEPTH),
           (SCREEN_R, HEAD_HALF_D), (HALO_IN, HEAD_HALF_D),
           (HALO_IN, HEAD_HALF_D-HALO_DEPTH), (HALO_OUT, HEAD_HALF_D-HALO_DEPTH),
           (HALO_OUT, HEAD_HALF_D), (HEAD_R-RIM_R, HEAD_HALF_D)]
shell_p += arc(HEAD_R-RIM_R, HEAD_HALF_D-RIM_R, RIM_R, 90, 0)
shell_p += [(HEAD_R, -(HEAD_HALF_D-RIM_R))]
shell_p += arc(HEAD_R-RIM_R, -(HEAD_HALF_D-RIM_R), RIM_R, 0, -90)
shell_p += [(0.0, -HEAD_HALF_D)]
shell = head_place(revolve(shell_p))
shell += revolve([(0.0,NECK_Z0),(NECK_R_BOT,NECK_Z0),(NECK_R_TOP,NECK_Z1),(0.0,NECK_Z1)])
base_p = [(0.0,0.0),(BASE_R-BASE_FILLET,0.0)]
base_p += arc(BASE_R-BASE_FILLET, BASE_FILLET, BASE_FILLET, -90, 0)
base_p += [(BASE_R, BASE_H-BASE_FILLET)]
base_p += arc(BASE_R-BASE_FILLET, BASE_H-BASE_FILLET, BASE_FILLET, 0, 90)
base_p += [(0.0, BASE_H)]
shell += revolve(base_p)

# 2. knurled rim sleeve around the puck edge
kz = HEAD_HALF_D - RIM_R + 0.6
knurl_loop = [(HEAD_R-1.6, -kz), (HEAD_R+0.9, -kz), (HEAD_R+0.9, kz), (HEAD_R-1.6, kz)]
knurl = head_place(revolve_loop(knurl_loop,
        radial=lambda a: KNURL_AMP*math.sin(KNURL_TEETH*a)))

# 3. diffuser ring, sitting proud of the face by 0.6
df = HEAD_HALF_D - HALO_DEPTH
diff_loop = [(HALO_IN, df), (HALO_OUT, df), (HALO_OUT, HEAD_HALF_D+0.6), (HALO_IN, HEAD_HALF_D+0.6)]
diffuser = head_place(revolve_loop(diff_loop))

# 4. screen disc filling the recess, flush
sz = HEAD_HALF_D - SCREEN_DEPTH
screen = head_place(revolve([(0.0, sz), (SCREEN_R, sz), (SCREEN_R, HEAD_HALF_D-0.4), (0.0, HEAD_HALF_D-0.4)]))

# 5. push-to-talk key
btn_p = [(0.0,0.0),(BTN_R,0.0),(BTN_R,BTN_OUT-1.2)]
btn_p += arc(BTN_R-1.2, BTN_OUT-1.2, 1.2, 0, 90, 10)
btn_p += [(0.0, BTN_OUT)]
button = head_place(rot_z(move(rot_y(revolve(btn_p,64), 90), HEAD_R-2.0, 0, 0), BTN_ANGLE))

# 6. base pad
pad = revolve([(0.0,-0.9),(BASE_R-9,-0.9),(BASE_R-9,1.2),(0.0,1.2)])

BODIES = [("shell", shell), ("knurl", knurl), ("diffuser", diffuser),
          ("screen", screen), ("button", button), ("pad", pad)]

COLOURWAYS = {
    "graphite": {"shell":"#33383F","knurl":"#1B1E23","diffuser":"#FF8C42",
                 "screen":"#0A100C","button":"#FF8C42","pad":"#121417"},
    "white":    {"shell":"#F1F3F5","knurl":"#C6CBD2","diffuser":"#4C8DFF",
                 "screen":"#EDF1F6","button":"#4C8DFF","pad":"#272C33"},
}

# ----------------------------- writers -----------------------------
def normal(t):
    (ax,ay,az),(bx,by,bz),(cx,cy,cz) = t
    ux,uy,uz = bx-ax,by-ay,bz-az; vx,vy,vz = cx-ax,cy-ay,cz-az
    nx,ny,nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
    L = math.sqrt(nx*nx+ny*ny+nz*nz) or 1.0
    return nx/L, ny/L, nz/L

def write_stl(path, tris, name):
    with open(path,"wb") as f:
        f.write(name.encode()[:79].ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            f.write(struct.pack("<3f", *normal(t)))
            for v in t: f.write(struct.pack("<3f", *v))
            f.write(struct.pack("<H", 0))

def dedup(tris):
    vi, verts, faces = {}, [], []
    for t in tris:
        idx = []
        for v in t:
            k = (round(v[0],4), round(v[1],4), round(v[2],4))
            if k not in vi:
                vi[k] = len(verts); verts.append(k)
            idx.append(vi[k])
        if idx[0]!=idx[1] and idx[1]!=idx[2] and idx[0]!=idx[2]:
            faces.append(idx)
    return verts, faces

def write_3mf(path, colours):
    NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    mats = "".join(
        f'<base name="{n}" displaycolor="{colours[n]}FF"/>' for n,_ in BODIES)
    objs, items = [], []
    for i,(name,tris) in enumerate(BODIES):
        verts, faces = dedup(tris)
        oid = i+2
        vx = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x,y,z in verts)
        tx = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a,b,c in faces)
        objs.append(f'<object id="{oid}" type="model" pid="1" pindex="{i}" name="{name}">'
                    f'<mesh><vertices>{vx}</vertices><triangles>{tx}</triangles></mesh></object>')
        items.append(f'<item objectid="{oid}"/>')
    model = (f'<?xml version="1.0" encoding="UTF-8"?>'
             f'<model unit="millimeter" xmlns="{NS}"><resources>'
             f'<basematerials id="1">{mats}</basematerials>'
             f'{"".join(objs)}</resources><build>{"".join(items)}</build></model>')
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)

# ----------------------------- run -----------------------------
os.makedirs("parts", exist_ok=True)
for name, tris in BODIES:
    write_stl(f"parts/Vigil-{name}.stl", tris, f"Vigil {name}")
    print(f"parts/Vigil-{name}.stl  {len(tris)} tris")

write_stl("Vigil-Concept.stl", sum((t for _,t in BODIES), []), "Vigil concept")
for cw, cols in COLOURWAYS.items():
    write_3mf(f"Vigil-{cw}.3mf", cols)
    print(f"Vigil-{cw}.3mf")
