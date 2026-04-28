plate = bd.Box(25, 20, 2)
ear1 = bd.Box(6, 6, 2).translate((-15.5, 7, 0))
ear2 = bd.Box(6, 6, 2).translate((-15.5, -7, 0))
hole1 = bd.Cylinder(1.2, 3).translate((-15.5, 7, 0))
hole2 = bd.Cylinder(1.2, 3).translate((-15.5, -7, 0))
result = (plate + ear1 + ear2) - hole1 - hole2