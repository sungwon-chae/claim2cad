# Claim2CAD — 60-second demo script

Use this when recording a screen capture for the README hero. Times are
approximate; the goal is "from raw claim text to bidirectional highlight
in under one minute".

| t (s) | Pane                | Action                                                                                                       |
|-------|---------------------|--------------------------------------------------------------------------------------------------------------|
| 0–2   | Terminal            | `cat examples/golden_robot_arm/claim.txt` — viewer reads the patent claim aloud.                            |
| 2–5   | Terminal            | `make demo-all` — pipeline runs all 3 examples; logs scroll past in <2 s per example.                       |
| 5–8   | Terminal            | `make viewer-dev` — Vite serves http://localhost:4179.                                                      |
| 8–14  | Browser             | The viewer loads with `golden_robot_arm` selected. Left pane: claim text with underlined element spans. Right pane: orbiting 3D model.|
| 14–22 | Browser             | Hover "first link" → corresponding cylinder lights up grey, others dim.                                     |
| 22–30 | Browser             | Click "first link" → cylinder turns gold, panel scrolls so the span stays in view.                          |
| 30–38 | Browser             | Click the gripper mesh in 3D → the panel jumps to the wherein clause "wherein the end effector includes a gripper" and highlights it.|
| 38–44 | Browser             | Toggle "Limitation focus: ON" → the dependent-claim sensor fades to 15 %, the independent-claim parts stay at 100 %.|
| 44–52 | Browser             | Switch the dropdown to `hinge_assembly` → 4 links + 4 joints render; same interactions work.                |
| 52–60 | Browser             | Switch to `planetary_gear` → sun, ring, carrier, 3 planets, input shaft. Click "carrier" → the central column highlights.|

The recording can be a short MP4 / GIF / animated SVG. If recording isn't
practical, capture three stills:

1. The split layout, no selection.
2. A claim-span click highlighting a 3D part.
3. A 3D part click scrolling the panel to the matching span.

Save them as `docs/diagrams/demo-1.png` etc. and link from the README.
