# Small stop tab/lug on U-shaped link member that contacts main member
# to limit pivot angle at max door opening position
w = 12.0   # width across link
h = 4.0    # tab height (protrusion)
t = 2.0    # thickness
base = bd.Box(w, t, h)
# Add a small chamfer on the contact edge
edges = base.edges().filter_by(bd.Axis.X).sort_by(bd.Axis.Z)[-1:]
result = bd.chamfer(edges, 0.5)