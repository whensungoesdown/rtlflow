#!/bin/bash
# Simulate c7blsu_stb with the animation scenario in ModelSim and write
# stb.vcd (all signals of the DUT, plus the clock) next to this script.
#
#   ./sim.sh                      uses the LSU RTL in LSU_RTL (default below)
#   LSU_RTL=/path/to/c7blsu/rtl ./sim.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LSU_RTL=${LSU_RTL:-/mnt/d/work/soc2/rtl/cpu7b/rtl/c7blsu/rtl}
WORK=${WORK:-/tmp/rtlflow_stb}

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK"
vlib work > /dev/null
vlog "$LSU_RTL/lib/swrvr_clib.v" "$LSU_RTL/c7blsu_stb.v" "$HERE/tb_stb_anim.v" > vlog.log 2>&1 \
    || { cat vlog.log; exit 1; }
vsim -c tb -do "vcd file $HERE/stb.vcd; vcd add -r /tb/dut/*; run -all; quit -f" > sim.log 2>&1
grep -E "\*\* (Error|Warning)" sim.log | head || true
echo "wrote $HERE/stb.vcd ($(wc -c < "$HERE/stb.vcd") bytes)"
