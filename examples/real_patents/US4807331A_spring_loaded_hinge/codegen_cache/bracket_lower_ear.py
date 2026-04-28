tab = bd.Part() + bd.Box(10, 8, 2, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER))
end = bd.Part() + bd.Cylinder(4, 2, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER)).translate((5, 0, 0))
blank = tab + end
hole = bd.Cylinder(2, 4, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER)).translate((5, 0, 0))
result = blank - hole