# Retainer finger: bent strip projecting upward, L-shape
# Vertical leg 10mm tall, horizontal foot 3mm, thickness 2mm, width 3mm
w = 3.0
t = 2.0
h = 10.0
foot = 3.0

vertical = bd.Pos(0, 0, h/2) * bd.Box(w, t, h)
horizontal = bd.Pos(0, -(t/2) - (foot/2) + t/2, h - t/2) * bd.Box(w, foot, t)

result = bd.Compound([vertical, horizontal])