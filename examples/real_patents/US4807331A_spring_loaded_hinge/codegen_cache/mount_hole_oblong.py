# Oblong slot 10x5mm through a thin flange, oriented per hints
# Build slot as two circles + rectangle, extrude, then position/rotate
L = 10.0
W = 5.0
T = 4.0  # flange thickness through which slot passes
r = W / 2.0
# Slot cross-section: rectangle of (L-W) x W with semicircles at ends
rect = bd.Rectangle(L - W, W)
c1 = bd.Pos((L - W) / 2.0, 0, 0) * bd.Circle(r)
c2 = bd.Pos(-(L - W) / 2.0, 0, 0) * bd.Circle(r)
slot_sk = rect + c1 + c2
slot = bd.extrude(slot_sk, amount=T)
# Apply desired rotation (0,90,0) then translation (45,8,15)
slot = bd.Rotation(0, 90, 0) * slot
slot = bd.Pos(45.0, 8.0, 15.0) * slot
result = slot