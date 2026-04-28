# Main member: L-shaped bracket plate with mounting wall and lower extension
w = 120.0
h = 70.0
t = 3.0
# Main plate profile (rough L/stepped shape as in figure)
pts = [(0,0),(w,0),(w,h),(0,h),(0,h*0.45),(w*0.15,h*0.45),(w*0.25,h*0.25),(w*0.35,h*0.25),(w*0.35,0)]
wire = bd.Polyline(*pts, close=True)
face = bd.make_face(wire)
plate = bd.extrude(face, amount=t)
# Top flange (bend at top edge '34')
top_flange = bd.Box(w, 15.0, t, align=(bd.Align.MIN, bd.Align.MIN, bd.Align.MIN))
top_flange = top_flange.translate((0, -15.0+t, h-t))
# Right side flange ('38')
side_flange = bd.Box(t, h, 12.0, align=(bd.Align.MIN, bd.Align.MIN, bd.Align.MIN))
side_flange = side_flange.translate((w-t, 0, t))
# Mounting slots (39')
slot1 = bd.Box(10.0, 6.0, t*3).translate((w*0.35, h*0.65, t/2))
slot2 = bd.Box(10.0, 6.0, t*3).translate((w*0.70, h*0.65, t/2))
body = plate + top_flange + side_flange
body = body - slot1 - slot2
result = body