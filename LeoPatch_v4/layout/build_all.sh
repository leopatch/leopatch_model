#!/bin/sh
# Rebuild the LeoPatch v4 board from the v3 board copy (v4_start.kicad_pcb) - run from the LeoPatch_v4 folder, KiCad closed.
set -e
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
VPY=${VPY:-$HOME/.venvs/leopatch-axon/bin/python}
T=${TMPDIR:-/tmp}/leopatch_v4; mkdir -p $T
cp layout/v4_start.kicad_pcb LeoPatch_v4.kicad_pcb
$CLI sch export netlist --format kicadxml -o $T/net.xml LeoPatch_v4.kicad_sch
$PY layout/build_v4_pcb.py LeoPatch_v4.kicad_pcb $T/net.xml
$PY layout/dump_geom.py LeoPatch_v4.kicad_pcb $T/geom.json
$VPY layout/route_new.py $T/geom.json $T/routes1.json "" layout/route_order.json
# pass 2: same order, analog nets keep 0.5 mm away from where pass 1 put the switching lines (and vice versa)
$VPY layout/route_new.py $T/geom.json $T/routes.json "" layout/route_order.json $T/routes1.json
$PY layout/apply_new_routes.py LeoPatch_v4.kicad_pcb $T/routes.json
$PY layout/refill.py LeoPatch_v4.kicad_pcb
$CLI pcb drc --schematic-parity --format json -o layout/drc.json LeoPatch_v4.kicad_pcb
python3 layout/make_jlc_files.py
