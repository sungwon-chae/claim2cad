od = 10.0
id_ = 5.0
th = 1.5
outer = bd.Cylinder(radius=od/2, height=th)
inner = bd.Cylinder(radius=id_/2, height=th+0.2)
result = outer - inner