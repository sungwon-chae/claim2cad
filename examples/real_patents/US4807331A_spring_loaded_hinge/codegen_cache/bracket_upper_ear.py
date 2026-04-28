w, h, t, hole = 10.0, 8.0, 2.0, 4.0
r = h/2
tab = bd.Part() + bd.Box(w - h, h, t, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER))
tab += bd.Cylinder(r, t, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER)).locate(bd.Location((-(w-h)/2, 0, 0)))
tab += bd.Cylinder(r, t, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER)).locate(bd.Location(((w-h)/2, 0, 0)))
tab -= bd.Cylinder(hole/2, t*2, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER)).locate(bd.Location(((w-h)/2, 0, 0)))
result = tab