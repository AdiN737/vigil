"""
Vigil concept enclosure -> STL
Form follows Vlad's "Minimal" render: a round puck head with an LED halo groove
and recessed screen, tilted back, held on a short neck and rounded base.

Concept / appearance model only. No internal bosses, no split line, no fasteners.
All dimensions in mm. Tweak the constants block and re-run.
"""
import math
import struct

# ----------------------------- parameters -----------------------------
SEG = 160          # revolve resolution

HEAD_R = 38.0      # puck outer radius
HEAD_HALF_D = 10.0 # half depth of the puck
RIM_R = 4.0        # rounded rim radius
SCREEN_R = 19.0    # circular screen recess radius
SCREEN_DEPTH = 3.0
HALO_IN = 25.0     # LED halo groove inner radius
HALO_OUT = 31.0    # LED halo groove outer radius
HALO_DEPTH = 3.4

HEAD_Z = 55.0      # head centre height above the desk
TILT_DEG = 12.0    # backward tilt of the face

NECK_R_BOT = 27.0
NECK_R_TOP = 19.0
NECK_Z0 = 11.0
NECK_Z1 = 27.0

BASE_R = 43.0
BASE_H = 16.0
BASE_FILLET = 6.0

BTN_R = 4.0        # acknowledge / push-to-talk key
BTN_OUT = 7.5      # how far it stands proud of the rim
BTN_ANGLE = 62.0   # position around the rim, 90 = straight up

# ----------------------------- helpers -----------------------------
Tri = tuple


def arc(cx, cz, r, a0, a1, n=14):
    """Points along an arc in the (r,z) profile plane."""
    return [
        (cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
         cz + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
        for i in range(n + 1)
    ]


def revolve(profile, seg=SEG):
    """Revolve a (r,z) profile around the z axis. Profile must start and end on r=0."""
    tris = []
    for i in range(seg):
        a0 = 2 * math.pi * i / seg
        a1 = 2 * math.pi * (i + 1) / seg
        c0, s0 = math.cos(a0), math.sin(a0)
        c1, s1 = math.cos(a1), math.sin(a1)
        for j in range(len(profile) - 1):
            r0, z0 = profile[j]
            r1, z1 = profile[j + 1]
            p00 = (r0 * c0, r0 * s0, z0)
            p01 = (r0 * c1, r0 * s1, z0)
            p10 = (r1 * c0, r1 * s0, z1)
            p11 = (r1 * c1, r1 * s1, z1)
            if r0 < 1e-9 and r1 < 1e-9:
                continue
            if r0 < 1e-9:
                tris.append((p00, p10, p11))
            elif r1 < 1e-9:
                tris.append((p00, p01, p10))
            else:
                tris.append((p00, p10, p11))
                tris.append((p00, p11, p01))
    return tris


def rot_x(tris, deg):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for t in tris:
        nt = []
        for (x, y, z) in t:
            nt.append((x, y * ca - z * sa, y * sa + z * ca))
        out.append(tuple(nt))
    return out


def rot_z(tris, deg):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for t in tris:
        nt = []
        for (x, y, z) in t:
            nt.append((x * ca - y * sa, x * sa + y * ca, z))
        out.append(tuple(nt))
    return out


def rot_y(tris, deg):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for t in tris:
        nt = []
        for (x, y, z) in t:
            nt.append((x * ca + z * sa, y, -x * sa + z * ca))
        out.append(tuple(nt))
    return out


def move(tris, dx, dy, dz):
    return [tuple((x + dx, y + dy, z + dz) for (x, y, z) in t) for t in tris]


# ----------------------------- head (puck) -----------------------------
# Profile runs from the centre of the screen recess, out across the face,
# through the halo groove, around the rounded rim, down the side and back.
head_profile = [(0.0, HEAD_HALF_D - SCREEN_DEPTH),
                (SCREEN_R, HEAD_HALF_D - SCREEN_DEPTH),
                (SCREEN_R, HEAD_HALF_D),
                (HALO_IN, HEAD_HALF_D),
                (HALO_IN, HEAD_HALF_D - HALO_DEPTH),
                (HALO_OUT, HEAD_HALF_D - HALO_DEPTH),
                (HALO_OUT, HEAD_HALF_D),
                (HEAD_R - RIM_R, HEAD_HALF_D)]
head_profile += arc(HEAD_R - RIM_R, HEAD_HALF_D - RIM_R, RIM_R, 90, 0)
head_profile += [(HEAD_R, -(HEAD_HALF_D - RIM_R))]
head_profile += arc(HEAD_R - RIM_R, -(HEAD_HALF_D - RIM_R), RIM_R, 0, -90)
head_profile += [(0.0, -HEAD_HALF_D)]

head = revolve(head_profile)

# acknowledge / push-to-talk key: a small capsule standing proud of the rim
btn_profile = [(0.0, 0.0), (BTN_R, 0.0), (BTN_R, BTN_OUT - 1.2)]
btn_profile += arc(BTN_R - 1.2, BTN_OUT - 1.2, 1.2, 0, 90, 8)
btn_profile += [(0.0, BTN_OUT)]
btn = revolve(btn_profile, 48)
btn = rot_y(btn, 90)                                  # lay it on its side
btn = move(btn, HEAD_R - 2.0, 0.0, 0.0)               # push out to the rim
btn = rot_z(btn, BTN_ANGLE)                           # around the rim

head = head + btn
# stand the puck up and tilt the face back
head = rot_x(head, -(90.0 - TILT_DEG))
head = move(head, 0.0, 0.0, HEAD_Z)

# ----------------------------- neck -----------------------------
neck = revolve([(0.0, NECK_Z0), (NECK_R_BOT, NECK_Z0),
                (NECK_R_TOP, NECK_Z1), (0.0, NECK_Z1)])

# ----------------------------- base -----------------------------
base_profile = [(0.0, 0.0), (BASE_R - BASE_FILLET, 0.0)]
base_profile += arc(BASE_R - BASE_FILLET, BASE_FILLET, BASE_FILLET, -90, 0)
base_profile += [(BASE_R, BASE_H - BASE_FILLET)]
base_profile += arc(BASE_R - BASE_FILLET, BASE_H - BASE_FILLET, BASE_FILLET, 0, 90)
base_profile += [(0.0, BASE_H)]
base = revolve(base_profile)

mesh = head + neck + base

# ----------------------------- write binary STL -----------------------------
def normal(t):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    L = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / L, ny / L, nz / L


with open("Vigil-Concept.stl", "wb") as f:
    f.write(b"Vigil concept enclosure - appearance model".ljust(80, b" "))
    f.write(struct.pack("<I", len(mesh)))
    for t in mesh:
        f.write(struct.pack("<3f", *normal(t)))
        for v in t:
            f.write(struct.pack("<3f", *v))
        f.write(struct.pack("<H", 0))

xs = [v[0] for t in mesh for v in t]
ys = [v[1] for t in mesh for v in t]
zs = [v[2] for t in mesh for v in t]
print(f"triangles: {len(mesh)}")
print(f"bounding box mm: X {max(xs)-min(xs):.1f}  Y {max(ys)-min(ys):.1f}  Z {max(zs)-min(zs):.1f}")
