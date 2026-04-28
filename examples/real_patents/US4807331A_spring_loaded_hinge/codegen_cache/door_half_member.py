# U-shaped door-half channel member
H = 120.0  # height
W = 40.0   # sidewall depth
B = 50.0   # bight width
T = 3.0    # wall thickness

# Outer box
outer = bd.Box(B, W, H, align=(bd.Align.CENTER, bd.Align.MIN, bd.Align.CENTER))
# Inner cavity (open on +Y side, forming U when viewed from top)
inner = bd.Box(B - 2*T, W, H - 2*T, align=(bd.Align.CENTER, bd.Align.MIN, bd.Align.CENTER))
inner = bd.Pos(0, T, 0) * inner
channel = outer - inner

# Hinge pin hole (39') through one sidewall near top
hole = bd.Cylinder(2.5, B + 2, rotation=(0, 90, 0))
hole = bd.Pos(0, W/2, H/4) * hole
channel = channel - hole

result = channel