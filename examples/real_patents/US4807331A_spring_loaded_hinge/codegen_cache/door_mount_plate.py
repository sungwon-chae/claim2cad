plate = bd.Box(30, 25, 2)
tab1 = bd.Box(8, 25, 2).translate((19, 0, 0))
hole1 = bd.Cylinder(1.5, 3).translate((21, 0, 0))
tab2 = bd.Box(8, 25, 2).translate((-19, 0, 0))
hole2 = bd.Cylinder(1.5, 3).translate((-21, 0, 0))
result = (plate + tab1 + tab2) - hole1 - hole2