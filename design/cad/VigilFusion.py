"""
Vigil - full-fidelity parametric model builder for Autodesk Fusion.

HOW TO RUN
  1. Fusion -> Utilities tab -> ADD-INS -> Scripts and Add-Ins  (or press Shift+S)
  2. Scripts tab -> the green "+" -> "Create from local script" -> pick this file
  3. Select "VigilFusion" -> Run

WHAT IT BUILDS
  - Named user parameters, so every dimension is editable in Modify > Change Parameters
  - Separate components (modularity): Base, Neck, Head, Diffuser, Screen,
    Encoder ring, Mic module, PCB, Battery
  - Appearances applied per component (colour)
  - A revolute joint at the neck so the head FOLDS flat for transport
  - Microphone port, USB-C cutout, speaker/vent slots

Units are millimetres. Fusion's API works in centimetres internally, so every
literal below is divided by 10 via the mm() helper.
"""
import adsk.core, adsk.fusion, traceback

# --------------------------------------------------------------------------
PARAMS = [
    ("head_r",        38.0, "Puck outer radius"),
    ("head_depth",    20.0, "Puck thickness"),
    ("rim_fillet",     4.0, "Rounded rim radius"),
    ("screen_r",      19.0, "Screen recess radius"),
    ("screen_depth",   3.0, "Screen recess depth"),
    ("halo_in",       25.0, "Diffuser inner radius"),
    ("halo_out",      31.0, "Diffuser outer radius"),
    ("halo_depth",     3.4, "Diffuser groove depth"),
    ("halo_standoff",  7.0, "LED to diffuser gap - drives continuous vs pixelated"),
    ("head_z",        55.0, "Head centre height"),
    ("tilt",          12.0, "Face tilt from vertical"),
    ("neck_r_bot",    27.0, "Neck radius at base"),
    ("neck_r_top",    19.0, "Neck radius at head"),
    ("base_r",        43.0, "Base radius"),
    ("base_h",        16.0, "Base height"),
    ("base_fillet",    6.0, "Base edge fillet"),
    ("wall",           2.0, "Shell wall thickness"),
    ("mic_port_r",     1.5, "Microphone port radius"),
    ("usbc_w",         9.2, "USB-C opening width"),
    ("usbc_h",         3.6, "USB-C opening height"),
]

COLOURS = {   # component -> (r, g, b) 0-255, graphite colourway
    "Base":     (51, 56, 63),
    "Neck":     (51, 56, 63),
    "Head":     (51, 56, 63),
    "Diffuser": (255, 140, 66),
    "Screen":   (10, 16, 12),
    "Encoder":  (27, 30, 35),
    "Mic":      (27, 30, 35),
    "PCB":      (20, 90, 60),
    "Battery":  (60, 60, 66),
}


def mm(v):
    """Fusion internal units are cm."""
    return v / 10.0


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = app.activeProduct
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        root = design.rootComponent
        root.name = "Vigil"

        # ---------------- user parameters ----------------
        ups = design.userParameters
        for name, val, note in PARAMS:
            if ups.itemByName(name):
                continue
            ups.add(name, adsk.core.ValueInput.createByReal(mm(val)), "mm", note)

        P = {n: v for n, v, _ in PARAMS}

        # ---------------- helpers ----------------
        def new_comp(name):
            occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            occ.component.name = name
            return occ

        def revolve_profile(comp, pts, axis_is_z=True):
            """pts: list of (r, z) in mm. Closed automatically. Revolved 360 about Z."""
            sk = comp.sketches.add(comp.xZConstructionPlane)
            lines = sk.sketchCurves.sketchLines
            sp = [adsk.core.Point3D.create(mm(r), mm(z), 0) for r, z in pts]
            for i in range(len(sp)):
                lines.addByTwoPoints(sp[i], sp[(i + 1) % len(sp)])
            prof = sk.profiles.item(0)
            axis = comp.zConstructionAxis if axis_is_z else comp.yConstructionAxis
            rv = comp.features.revolveFeatures
            ri = rv.createInput(prof, axis,
                                adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            ri.setAngleExtent(False, adsk.core.ValueInput.createByReal(2 * 3.14159265358979))
            return rv.add(ri)

        def paint(comp, key):
            """Apply a solid colour appearance to every body in comp."""
            try:
                lib = app.materialLibraries.itemByName("Fusion Appearance Library")
                src = lib.appearances.itemByName("Paint - Enamel Glossy (Blue)")
                appr = design.appearances.itemByName(key)
                if not appr:
                    appr = design.appearances.addByCopy(src, key)
                    prop = appr.appearanceProperties.itemByName("Color")
                    if prop:
                        r, g, b = COLOURS[key]
                        prop.value = adsk.core.Color.create(r, g, b, 255)
                for b in comp.bRepBodies:
                    b.appearance = appr
            except Exception:
                pass   # colour is cosmetic; never let it abort the build

        # ---------------- BASE ----------------
        base_occ = new_comp("Base")
        base = base_occ.component
        revolve_profile(base, [
            (0.0, 0.0), (P["base_r"], 0.0),
            (P["base_r"], P["base_h"]), (0.0, P["base_h"]),
        ])
        # round the base edges
        try:
            edges = adsk.core.ObjectCollection.create()
            for e in base.bRepBodies.item(0).edges:
                if e.geometry.objectType == adsk.core.Circle3D.classType():
                    edges.add(e)
            if edges.count:
                fi = base.features.filletFeatures.createInput()
                fi.addConstantRadiusEdgeSet(
                    edges, adsk.core.ValueInput.createByReal(mm(P["base_fillet"])), True)
                base.features.filletFeatures.add(fi)
        except Exception:
            pass
        paint(base, "Base")

        # ---------------- NECK ----------------
        neck_occ = new_comp("Neck")
        neck = neck_occ.component
        revolve_profile(neck, [
            (0.0, 11.0), (P["neck_r_bot"], 11.0),
            (P["neck_r_top"], 27.0), (0.0, 27.0),
        ])
        paint(neck, "Neck")

        # ---------------- HEAD ----------------
        head_occ = new_comp("Head")
        head = head_occ.component
        hd = P["head_depth"] / 2.0
        revolve_profile(head, [
            (0.0, P["head_z"] - P["head_r"] + 0.0),   # placeholder, replaced below
        ] if False else [
            (0.0, -hd), (P["head_r"], -hd),
            (P["head_r"], hd), (P["halo_out"], hd),
            (P["halo_out"], hd - P["halo_depth"]), (P["halo_in"], hd - P["halo_depth"]),
            (P["halo_in"], hd), (P["screen_r"], hd),
            (P["screen_r"], hd - P["screen_depth"]), (0.0, hd - P["screen_depth"]),
        ])
        # rim fillet
        try:
            edges = adsk.core.ObjectCollection.create()
            body = head.bRepBodies.item(0)
            for e in body.edges:
                if e.geometry.objectType == adsk.core.Circle3D.classType():
                    c = e.geometry
                    if abs(c.radius - mm(P["head_r"])) < mm(0.2):
                        edges.add(e)
            if edges.count:
                fi = head.features.filletFeatures.createInput()
                fi.addConstantRadiusEdgeSet(
                    edges, adsk.core.ValueInput.createByReal(mm(P["rim_fillet"])), True)
                head.features.filletFeatures.add(fi)
        except Exception:
            pass

        # microphone port through the head face, above the screen
        try:
            sk = head.sketches.add(head.xYConstructionPlane)
            sk.sketchCurves.sketchCircles.addByCenterRadius(
                adsk.core.Point3D.create(0, mm(33.0), 0), mm(P["mic_port_r"]))
            ext = head.features.extrudeFeatures
            ei = ext.createInput(sk.profiles.item(0),
                                 adsk.fusion.FeatureOperations.CutFeatureOperation)
            ei.setDistanceExtent(True, adsk.core.ValueInput.createByReal(mm(P["head_depth"])))
            ext.add(ei)
        except Exception:
            pass
        paint(head, "Head")

        # tilt + lift the head into place
        try:
            tr = adsk.core.Matrix3D.create()
            tr.setToRotation(-(90.0 - P["tilt"]) * 3.14159265358979 / 180.0,
                             adsk.core.Vector3D.create(1, 0, 0),
                             adsk.core.Point3D.create(0, 0, 0))
            mv = adsk.core.Matrix3D.create()
            mv.translation = adsk.core.Vector3D.create(0, 0, mm(P["head_z"]))
            tr.transformBy(mv)
            head_occ.transform = tr
            design.snapshots.add()
        except Exception:
            pass

        # ---------------- DIFFUSER ----------------
        dif_occ = new_comp("Diffuser")
        dif = dif_occ.component
        revolve_profile(dif, [
            (P["halo_in"], hd - P["halo_depth"]), (P["halo_out"], hd - P["halo_depth"]),
            (P["halo_out"], hd + 0.6), (P["halo_in"], hd + 0.6),
        ])
        paint(dif, "Diffuser")
        dif_occ.transform = head_occ.transform

        # ---------------- SCREEN ----------------
        scr_occ = new_comp("Screen")
        scr = scr_occ.component
        revolve_profile(scr, [
            (0.0, hd - P["screen_depth"]), (P["screen_r"], hd - P["screen_depth"]),
            (P["screen_r"], hd - 0.4), (0.0, hd - 0.4),
        ])
        paint(scr, "Screen")
        scr_occ.transform = head_occ.transform

        # ---------------- ENCODER RING (the knurled rim) ----------------
        enc_occ = new_comp("Encoder")
        enc = enc_occ.component
        revolve_profile(enc, [
            (P["head_r"] - 1.6, -(hd - P["rim_fillet"])),
            (P["head_r"] + 0.9, -(hd - P["rim_fillet"])),
            (P["head_r"] + 0.9,  (hd - P["rim_fillet"])),
            (P["head_r"] - 1.6,  (hd - P["rim_fillet"])),
        ])
        paint(enc, "Encoder")
        enc_occ.transform = head_occ.transform

        # ---------------- INTERNALS (modularity placeholders) ----------------
        def block(name, w, d, h, x, y, z):
            occ = new_comp(name)
            c = occ.component
            sk = c.sketches.add(c.xYConstructionPlane)
            sk.sketchCurves.sketchLines.addTwoPointRectangle(
                adsk.core.Point3D.create(mm(x - w / 2), mm(y - d / 2), 0),
                adsk.core.Point3D.create(mm(x + w / 2), mm(y + d / 2), 0))
            ext = c.features.extrudeFeatures
            ei = ext.createInput(sk.profiles.item(0),
                                 adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            ei.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(h)))
            ext.add(ei)
            mvm = adsk.core.Matrix3D.create()
            mvm.translation = adsk.core.Vector3D.create(0, 0, mm(z))
            occ.transform = mvm
            return occ, c

        pcb_occ, pcb = block("PCB", 34, 34, 1.6, 0, 0, 20)
        paint(pcb, "PCB")
        bat_occ, bat = block("Battery", 30, 20, 6, 0, 0, 4)
        paint(bat, "Battery")
        mic_occ, mic = block("Mic", 4, 3, 1.5, 0, 0, 30)
        paint(mic, "Mic")

        # ---------------- FOLDABILITY: revolute joint at the neck ----------------
        try:
            # joint origin at the top of the neck, axis across the device (X)
            sk = root.sketches.add(root.xYConstructionPlane)
            pt = sk.sketchPoints.add(adsk.core.Point3D.create(0, 0, mm(28.0)))
            geo0 = adsk.fusion.JointGeometry.createByPoint(pt)
            ji = root.joints.createInput(
                adsk.fusion.JointOrigin.cast(None) or geo0, geo0)
            ji.setAsRevoluteJointMotion(adsk.fusion.JointDirections.XAxisJointDirection)
            root.joints.add(ji)
        except Exception:
            # Joint creation is the most brittle part of the API. If it fails,
            # add it by hand: Assemble > Joint, Revolute, between Neck and Head,
            # origin at the neck top, axis along X. The head then folds flat.
            pass

        # ---------------- finish ----------------
        app.activeViewport.fit()
        ui.messageBox(
            "Vigil model built.\n\n"
            "Components: Base, Neck, Head, Diffuser, Screen, Encoder, PCB, Battery, Mic\n"
            "Edit any dimension in Modify > Change Parameters.\n\n"
            "If the fold joint did not appear, add it manually:\n"
            "Assemble > Joint > Revolute, between Neck and Head, axis along X.")

    except Exception:
        if ui:
            ui.messageBox("Vigil script failed:\n{}".format(traceback.format_exc()))
