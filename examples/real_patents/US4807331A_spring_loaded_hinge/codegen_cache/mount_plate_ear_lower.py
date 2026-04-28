# Lower mount plate ear: rolled tab 8mm wide with 4mm thru hole
w = 8.0
t = 1.5
r_out = 5.0
r_in = r_out - t
hole_d = 4.0

# Create a C-shaped (rolled) profile in XZ plane, extrude along Y (width)
outer = bd.Plane.XZ * bd.Circle(r_out)
inner = bd.Plane.XZ * bd.Circle(r_in)
ring = outer - inner
# Cut the bottom half to make it a rolled/curled tab (keep upper ~270 deg)
cutter = bd.Plane.XZ * bd.Rectangle(2*r_out, r_out, align=(bd.Align.CENTER, bd.Align.MAX))
profile = ring - cutter
tab = bd.extrude(profile, amount=w/2) + bd.extrude(profile, amount=-w/2)

# Flat flange extending downward from the roll with a thru hole
flange = bd.Pos(0, 0, -r_out/2) * bd.Box(2*r_out, w, r_out)
body = tab + flange

# Thru hole through the rolled portion along Y
hole = bd.Pos(0, 0, 0) * (bd.Plane.XZ * bd.Circle(hole_d/2))
hole_solid = bd.extrude(hole, amount=w, both=True)
result = body - hole_solid