shaft = bd.Pos(0,0,14) * bd.Cylinder(radius=2.5, height=28)
head = bd.Pos(0,0,28.5) * bd.Cylinder(radius=4, height=2)
result = bd.Compound(children=[shaft, head])