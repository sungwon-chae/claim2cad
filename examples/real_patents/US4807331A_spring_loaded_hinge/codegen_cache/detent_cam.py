r=6.0
th=4.0
n=6
lobe=1.2
pts=[]
for i in range(180):
    a=math.radians(i*2)
    rr=r+lobe*math.cos(n*a)
    pts.append((rr*math.cos(a),rr*math.sin(a)))
wire=bd.Polyline(*pts,close=True)
face=bd.make_face(wire)
result=bd.extrude(face,amount=th)