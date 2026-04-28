plate = bd.Box(20, 12, 2)
slot_body = bd.Box(12, 5, 4)
end1 = bd.Pos(-6, 0, 0) * bd.Cylinder(2.5, 4)
end2 = bd.Pos(6, 0, 0) * bd.Cylinder(2.5, 4)
slot = slot_body + end1 + end2
result = plate - slot