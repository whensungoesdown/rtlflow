#!/bin/bash
# c7blsu and c7blsu_stb from a VCD of the whole CPU (test109_stb_write_error).
#
# 1. In WSL, simulate test109 (it logs every signal to result.wlf) and convert
#    the WLF to a VCD:
#      cd /mnt/d/work/soc2/rtl/cpu7b/simulation/test109_stb_write_error
#      bash simulate.sh          # needs sram.mif, e.g. from /d/work/test109_build/inst_ram.mif
#      wlf2vcd result.wlf -o /mnt/d/work/rtlflow/examples/c7blsu/test109.vcd
#
# 2. Then, in this directory: ./run.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
RF=$HERE/../../rtlflow.py
CPU=${CPU:-$HERE/../../../soc2/rtl/cpu7b/rtl}
L=$CPU/c7blsu/rtl

# the LSU, with the DTLB kept as one block; STB_BUFFER as in simulate.sh (-GSTB_BUFFER=1)
python "$RF" "$L/lib/swrvr_clib.v" "$L/c7blsu_stb.v" "$L/c7blsu.v" -I "$L" -I "$CPU" \
    --lib "$CPU/c7btlb/rtl/c7btlb.v" --top c7blsu --param STB_BUFFER=1 \
    --vcd "$HERE/test109.vcd" -o "$HERE/c7blsu.html" 2>&1 | grep -v "^Warning: Replacing memory"

# the store buffer alone, from the same VCD (the scope u_lsu.u_stb is found automatically)
python "$RF" "$L/lib/swrvr_clib.v" "$L/c7blsu_stb.v" --top c7blsu_stb \
    --vcd "$HERE/test109.vcd" -o "$HERE/c7blsu_stb.html"
