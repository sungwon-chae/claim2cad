w, d, t = 30.0, 20.0, 2.5
flange = bd.Box(w, d, t, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER))
hole = bd.Cylinder(3.0, t+1, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER))
result = flange - hole