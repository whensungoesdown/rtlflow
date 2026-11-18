# rtlflow

`rtlflow` turns a synchronous Verilog module into a top-to-bottom block
diagram and steps through a simulation of it, cycle by cycle, in a web page.

```
Inputs      the module's input ports                      orange
Registers   flip-flops: D strip, Q value, clock triangle  pink
Logic       the combinational signals                     green
Outputs     the module's output ports                     purple
```

The diagram is generated from the Verilog: Yosys reads the module and every
**named signal** (port, `wire`, `reg`, generate-block wire) becomes a block.
The anonymous logic between two named signals (the `&`, `|`, `?:` of an
`assign`) is folded into the arrows, so the picture is at the level of the
names in the source, not of gates.

The values come from a **VCD** file written by any simulator (or a simple
text trace), sampled once per clock cycle. The output is a single HTML file
with no external dependencies: open it in a browser, or send it to someone.

## Requirements

- Python 3.
- Yosys: either `yosys` on the PATH, or `pip install yowasp-yosys` (a
  WebAssembly build, no system install; the first run takes a while).
- A browser (Edge, Chrome, Firefox).

For the browser test only: `pip install playwright` (it uses the installed
Edge or Chrome, no browser download).

## Usage

```bash
python rtlflow.py FILES.v ... --top MODULE [--vcd SIM.vcd] [-o OUT.html]
```

| Option | Meaning |
|---|---|
| `--top MODULE` | the module to draw; submodules are flattened into it |
| `-I DIR`, `-D NAME[=VAL]` | include directories and defines for Yosys |
| `--sv` | read all files as SystemVerilog (`.sv` files always are) |
| `--param NAME=VAL` | set a parameter of the top module, as `-GNAME=VAL` in the simulation (repeatable) |
| `--lib FILE` | read FILE for its ports only: each instance of its modules is one block (repeatable) |
| `--blackbox MODULE` | keep each instance of MODULE as one block instead of flattening it (repeatable) |
| `--vcd FILE` | the simulation dump |
| `--scope tb.dut` | the DUT instance in the VCD; found automatically if omitted |
| `--clock NAME` | the clock; found from the flip-flops if omitted |
| `--negedge` | sample at the falling edge instead of the rising edge |
| `--cycles A:B` | keep cycles A..B-1 only (Python slice: `100:`, `:50`) |
| `--trace FILE` | a text trace instead of a VCD, see below |
| `--hide REGEX` | hide signals whose name matches (repeatable) |
| `--only REGEX` | show only the signals whose name matches, hide the rest (repeatable) |
| `--layout FILE.json` | block positions saved from the page |
| `--title TEXT` | page title |

Without `--vcd`/`--trace` the page shows the diagram only, which is
enough to arrange the layout.

The script prints what it found, e.g.

```
c7blsu_stb: 14 input, 14 output, 11 reg, 27 comb, 112 edges; hidden: clk, resetn
41 cycles from scope tb.dut; no values for: -
wrote examples/c7blsu_stb/c7blsu_stb.html (81 kB)
```

"no values for" lists the visible blocks that are not in the VCD. Dump all
signals of the DUT, including the internal ones.

## A module inside a bigger simulation

The VCD does not have to come from a testbench of the module. A dump of the
whole CPU works as well: rtlflow looks for the scope (instance) whose
signals match the module best, and reads only those signals. Use `--scope`
when the module is instantiated more than once.

`examples/c7blsu/run.sh` does this with test109 (the STB write error
test) of cpu7b:

```bash
# in WSL: simulate the whole CPU, it logs every signal to result.wlf
cd /mnt/d/work/soc2/rtl/cpu7b/simulation/test109_stb_write_error
bash simulate.sh
wlf2vcd result.wlf -o /mnt/d/work/rtlflow/examples/c7blsu/test109.vcd

# then
bash examples/c7blsu/run.sh
```

```
c7blsu: 57 input, 49 output, 78 comb, 43 reg, 1 inst, 475 edges; hidden: clk, resetn
2535 cycles from scope top_tb.u_top.u_c7b.u_core.u_exu.u_lsu; no values for: -
c7blsu_stb: 14 input, 14 output, 11 reg, 27 comb, 112 edges; hidden: clk, resetn
2535 cycles from scope top_tb.u_top.u_c7b.u_core.u_exu.u_lsu.u_stb; no values for: -
```

Things to get right:

- **Parameters.** Build the diagram with the values the simulation used.
  test109 runs with `-GSTB_BUFFER=1`, so `run.sh` passes `--param
  STB_BUFFER=1`. With a different value Yosys removes the logic that is
  constant for that value.
- **Submodules.** All files of the module's hierarchy are needed. A
  submodule you don't want to see inside the diagram can be one block:
  `--lib c7btlb.v` reads the DTLB for its ports only, so `u_dtlb` is one
  block (blue) between its inputs and its outputs. `--blackbox MODULE` does
  the same for a module whose file is read normally.
- **What is shown of the flattened submodules.** Inside `c7blsu`, the STB
  (`u_stb`) is flattened: its register outputs are blocks (`u_stb.v_q`,
  `u_stb.err_q`, ...), and its logic (`pop`, `issue_start`, ...) is folded
  into the wires. To see the STB's logic, make a page for `c7blsu_stb`
  itself from the same VCD (the second command in `run.sh`).
- **ModelSim WLF.** `wlf2vcd` (part of ModelSim) converts a WLF file. The
  WLF has the signals that were logged (`add wave -recursive *` or
  `log -r /*`). test109's VCD is 38 MB and is read in about 3 s.
- **Many cycles.** All cycles go into the page (2535 cycles of the LSU make
  a 3.6 MB page). Use `--cycles A:B` to keep a window.

A whole LSU is about 230 blocks, which is too many to read at once. Use
**Focus** (below) or `--only`.

## The example: c7blsu_stb

```bash
# 1. simulate (ModelSim, in WSL here): writes examples/c7blsu_stb/stb.vcd
wsl bash -ic "bash /mnt/d/work/rtlflow/examples/c7blsu_stb/sim.sh"

# 2. generate the page
L=../soc2/rtl/cpu7b/rtl/c7blsu/rtl
python rtlflow.py $L/lib/swrvr_clib.v $L/c7blsu_stb.v --top c7blsu_stb \
    --vcd examples/c7blsu_stb/stb.vcd -o examples/c7blsu_stb/c7blsu_stb.html
```

`sim.sh` runs the testbench of the earlier animation (`tb_stb_anim.v`,
stores A-G) with `vcd file stb.vcd; vcd add -r /tb/dut/*`. With
other simulators:

| Simulator | Dump all DUT signals |
|---|---|
| ModelSim / Questa | `vsim -c tb -do "vcd file sim.vcd; vcd add -r /tb/dut/*; run -all; quit -f"` |
| Icarus Verilog | in the testbench: `initial begin $dumpfile("sim.vcd"); $dumpvars(0, tb.dut); end` |
| Verilator | `--trace`, and `Verilated::traceEverOn(true)` / `$dumpfile` + `$dumpvars` |

## The page

Each cycle has three steps:

1. **clock edge**: the registers show their new value; the ones that
   changed get an orange outline.
2. **signals**: the active signals light up as thick lavender arrows, from
   the inputs and the register outputs down to the outputs (a front sweeps
   down the page).
3. **next state**: the registers that change at the next edge show the new
   value on their D strip, and their D inputs are drawn in teal (thick when
   the source is active).

The side panel describes the step: which registers changed, the active
inputs and outputs, what each register will load and from which signals.

| Control | Action |
|---|---|
| `Prev` / `Next`, Left / Right | previous / next step |
| `« cycle` / `cycle »`, Up / Down, PageUp / PageDown | previous / next cycle |
| step buttons `1 2 3` | jump to a step of the current cycle |
| slider, Home / End | any step, first / last |
| `Play`, Space | advance every 1.3 s |
| `−` `Fit` `+` | zoom |
| `lit:` menu | which signals count as active, see below |
| `hidden (n)` menu | show a hidden block again |
| `Auto layout` | arrange all blocks again from scratch |
| `Save layout` / `Load layout` | write / read the layout as a JSON file |

The address ends in `#cycle.step` (e.g. `#16.1`), so a link can point to a
step.

**Active signals (`lit:`).**

- *non-zero*: any bit is 1. This is the default.
- *1-bit non-zero*: only single-bit signals light up. Use this when the data
  buses are non-zero all the time and hide the control flow.
- *changed*: the value differs from the previous cycle.

**Blocks.**

- Hover over a block to see its full value.
- Click a block to select it. Its wires are drawn dark, and the side panel
  shows its kind, width, source line, value, next value, and the blocks it
  comes from and goes to (as links).
- **Hide this block** removes the block. The wires through it are connected
  directly, from its sources to its destinations. This is how you simplify
  the diagram, e.g. to fold `paddr_sh` into `paddr_in`.
- **Focus** shows only the selected block, the blocks up to N levels before
  it (where its value comes from) and the blocks up to N levels after it
  (what it drives). The blocks in between that are hidden are bridged, so the
  wires still show the dependencies. The diagram is arranged again. **show
  all** in the `hidden` menu goes back to the full diagram. For example, focus
  on `u_stb.err_q` in the LSU page, 2 levels, to see the STB error path.
- **prev change / next change** jump to the previous / next cycle in which
  the selected signal changes value. With 2535 cycles this is how you find
  the cycles that matter (in test109: `u_stb.err_q` is set at cycle 53).
- The box after the cycle number jumps to a cycle (type it, Enter).
- **find value** looks for a value of the selected signal. **find ›** / Enter
  goes to the next cycle where the value *appears*, and **‹ find** /
  Shift+Enter to the previous one. A value that is held for several cycles
  counts once: the search jumps to the first cycle of each run. The message
  shows e.g. `cycle 53: 2 of 2, held 5 cycles`. The search wraps around at
  the end of the trace. Registers open at step 1 (clock edge), the other
  blocks at step 2 (signals).

  | Query | Meaning |
  |---|---|
  | `0001`, `01?1` | plain digits are read as shown in the block: binary for 8 bits or fewer, hex otherwise |
  | `70000000`, `7000_????` | hex (on a signal wider than 8 bits); `_` and spaces are ignored |
  | `0x1f`, `0b0101`, `0d31` | hex, binary, decimal |
  | `32'h7000_0000`, `4'b01?1`, `'d31` | Verilog literals |
  | `?` | any digit (a hex `?` is 4 bits) |
  | `x`, `z` | match only `x` / `z` bits in the dump |

  A value is padded with zeros on the left to the signal's width, so on
  `u_stb.v_q` (4 bits), `1` finds `0001`.

Clocks and resets are hidden from the start. Their names match
`(rst|reset)(_n|_l|n|...)`; add more with `--hide`.

**Arranging the layout.**

- Drag a block sideways to move it in its row, or up and down to move it to
  another row (rows are kept, a block snaps to the nearest one). The wires are
  routed again when you drop it.
- The layout (positions and hidden blocks) is kept in the browser's local
  storage for that module. To keep it with the design, click **Save layout**
  and pass the file with `--layout`:

  ```bash
  python rtlflow.py ... --top c7blsu_stb --vcd stb.vcd --layout c7blsu_stb.layout.json
  ```

  A layout written into the page this way replaces the one in local storage
  on the first load. Blocks that are new since the layout was saved are
  placed automatically.

## How the diagram is made

1. **Yosys**: `read_verilog; hierarchy -top; proc; flatten; opt_clean;
   write_json`. This gives a netlist of word-level cells (`$and`, `$mux`,
   `$eq`, `$dff`, ...) and the named wires.
2. **Blocks**: every bit gets an owner, the name it is shown under:
   input port, then module wire, then the Q wire of a flip-flop inside a
   flattened instance (e.g. `err_vaddr_reg.q`), then output port. Other
   wires inside instances (such as a library flop's `din`) are treated as
   anonymous logic. A block is a register if its bits are driven by
   flip-flops. Signals driven only by constants are dropped.
3. **Edges**: each block's inputs are traced back through the anonymous
   cells to the named signals they come from. For a register this is its D
   input (and enable, reset), not the clock.
4. **Layout, in the page**:
   - Rows are filled in this order: inputs, registers, the logic levels
     (longest path from the registers and inputs), outputs. A row wider than
     about 2200 px is split.
   - The order within each row is found by barycentre sweeps. The x
     positions come from an order-preserving least-squares fit
     towards the neighbours.
5. **Routing, in the page**:
   - Wires are orthogonal. A signal leaves its block at the bottom and runs
     along a horizontal track in the gap below its row.
   - If it has to cross rows, it goes through a free vertical channel
     between blocks, and then along a track in the gap above the destination.
   - Tracks are shared by all branches of one signal (junction dots mark the
     branches) and packed into lanes, and the gaps grow with their lane count.

**Values.**

- The VCD is sampled just before each active clock edge. That sample is the
  settled state of the cycle that began at the previous edge: the registers
  with their values for the cycle, and the inputs and logic in that cycle.
  Cycle *k* is the one that starts at edge *k* (counted from 0).
- Per-bit VCD variables (ModelSim writes vectors as `name [31]` ...) are put
  back together. Generate scopes such as `ld_cmp(0)` and `ld_cmp[0]` match
  the Yosys name `ld_cmp[0].ovl`.
- Values with `x`/`z` bits show `x`/`z` digits.

## Text trace format

`--trace FILE` takes one line per cycle, with `name=value` pairs and the
values in hex:

```
cyc=0 lsu_stb_push_ls2=1 lsu_stb_paddr_ls2=00001000 v_q=0 iss_q=0
cyc=1 lsu_stb_push_ls2=0 v_q=1 iss_q=0
```

- The names are the block names, as shown in the page.
- `cyc` (optional) is the cycle label.
- `x` stands for an unknown value.
- A signal that is missing from a line has no value in that cycle.

## Limits

- **One clock domain.** Multi-clock designs are drawn, but they are sampled
  on one clock.
- **Submodules are flattened**, unless they are given with `--lib` or
  `--blackbox`. A flattened submodule shows its register outputs; its logic
  is folded into the wires.
- **Big modules.** With more than about 100 blocks the automatic layout is
  dense. Use Focus, `--only` or Hide, and arrange the rest.
- **Memories** (`reg [..] mem [..]`) have not been tried yet.
- **No in-browser simulation yet.** The values must come from a
  simulation.

## Files

| File | Purpose |
|---|---|
| `rtlflow.py` | Command line: Yosys → signal graph, VCD/trace → values per cycle, writes the page |
| `viewer.html` | The page template: layout, routing, drawing, playback, editing (plain JavaScript) |
| `examples/c7blsu_stb/` | `tb_stb_anim.v`, `sim.sh`, `stb.vcd` and the generated `c7blsu_stb.html` |
| `examples/c7blsu/` | `run.sh`, `test109.vcd` (whole CPU) and the generated `c7blsu.html`, `c7blsu_stb.html` |
| `tests/browser_test.py` | Opens a page in Edge/Chrome, steps, drags, hides, reloads, saves a layout, reports JavaScript errors |
| `tests/focus_test.py` | Focus on a block, next change, show all, go to a cycle |
| `tests/search_test.py` | The value search: find forward/backward, the query parser |
| `tests/pic_trace.txt` | A small text trace for `pic.v`, to test `--trace` |
