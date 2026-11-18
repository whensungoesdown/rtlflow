"""rtlflow: show a synchronous Verilog module as a top-to-bottom block diagram
and step through a simulation of it, cycle by cycle, in a web page.

  inputs (top)  ->  registers  ->  logic  ->  outputs (bottom)

The diagram is generated from the Verilog with Yosys: every named signal of
the module becomes a block, the anonymous logic between named signals is
collapsed into the edges. The values come from a VCD file (or a text trace),
sampled once per clock cycle.

usage:
  python rtlflow.py FILE.v [FILE.v ...] --top MODULE [--vcd SIM.vcd] [-o OUT.html]

  -I DIR / -D NAME[=VAL]     include directories and defines for Yosys
  --sv                       read all files as SystemVerilog (.sv files always are)
  --param NAME=VAL           set a parameter of the top module (as -GNAME=VAL in the simulation)
  --lib FILE                 read FILE for its module ports only: each instance of it is one block
  --blackbox MODULE          keep each instance of MODULE as one block instead of flattening it
  --vcd FILE                 simulation dump; --scope tb.dut selects the DUT
                             instance (found automatically if omitted)
  --trace FILE               text trace instead: one line per cycle, name=hex pairs
  --clock NAME               clock of the module (found from the flip-flops)
  --negedge                  sample at the falling edge instead of the rising edge
  --cycles A:B               keep cycles A..B-1 only
  --only REGEX               show only signals whose name matches (repeatable);
                             the others are hidden, i.e. bridged
  --hide REGEX               hide signals whose name matches (repeatable);
                             clocks and resets are hidden by default
  --layout FILE.json         block positions saved from the page ("Save layout")
  --title TEXT               page title

Yosys: the yosys binary on the PATH, or `pip install yowasp-yosys`.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

REG_TYPES = {'$dff', '$dffe', '$adff', '$adffe', '$sdff', '$sdffe', '$sdffce', '$dffsr', '$dffsre',
             '$aldff', '$aldffe', '$dlatch', '$adlatch', '$dlatchsr', '$sr', '$ff'}
REG_PREFIX = ('$_DFF', '$_SDFF', '$_DFFE', '$_SDFFE', '$_SDFFCE', '$_DFFSR', '$_DFFSRE', '$_ALDFF',
              '$_DLATCH', '$_SR')
MEM_TYPES = {'$mem', '$mem_v2'}
CLOCK_PORTS = {'CLK', 'C', 'RD_CLK', 'WR_CLK'}
RESET_RE = r'(?i)^(.*_)?(rst|reset)(_?n|_?l|_?b)?$'


# ------------------------------------------------------------------ yosys
def run_yosys(files, top, incdirs, defines, sv=False, params=(), libs=(), boxes=()):
    out = tempfile.mktemp(suffix='.json')
    opts = ' '.join(['-I' + yp(d) for d in incdirs] + ['-D' + d for d in defines])
    rd = '; '.join('read_verilog %s %s %s "%s"' % ('-lib' if f in libs else '', '-sv' if sv or f.endswith('.sv') else '',
                                                    opts, yp(f)) for f in list(libs) + list(files))
    for b in boxes:
        rd += '; blackbox %s' % b
    chp = ' '.join('-chparam %s %s' % tuple(p.split('=', 1)) for p in params)
    script = '%s; hierarchy -check -top %s %s; proc; flatten; opt_clean; write_json "%s"' % (rd, top, chp, yp(out))
    if shutil.which('yosys'):
        cmd = ['yosys', '-q', '-p', script]
    else:
        try:
            import yowasp_yosys  # noqa: F401
        except ImportError:
            sys.exit('rtlflow: needs Yosys: put yosys on the PATH or `pip install yowasp-yosys`')
        cmd = [sys.executable, '-c', 'import sys, yowasp_yosys; sys.exit(yowasp_yosys.run_yosys(sys.argv[1:]))',
               '-q', '-p', script]
    r = subprocess.run(cmd)
    if r.returncode or not os.path.exists(out):
        sys.exit('rtlflow: Yosys failed')
    with open(out, encoding='utf-8') as f:
        d = json.load(f)
    os.remove(out)
    return d


def yp(p):
    return os.path.abspath(p).replace('\\', '/')


def is_reg(t):
    return t in REG_TYPES or t.startswith(REG_PREFIX)


# ------------------------------------------------------------------ graph
def build_graph(yj, top, hide):
    m = yj['modules'][top]
    ports = m['ports']
    nets = {n: v for n, v in m['netnames'].items() if not v.get('hide_name')}

    # who drives each bit
    driver = {}
    reg_bits, clock_bits = set(), set()
    for cn, c in m['cells'].items():
        t = c['type']
        dirs = c.get('port_directions', {})
        for p, bits in c['connections'].items():
            if dirs.get(p) == 'output':
                for b in bits:
                    if isinstance(b, int):
                        driver[b] = (cn, p)
                        if is_reg(t) or t in MEM_TYPES:
                            reg_bits.add(b)
            elif (is_reg(t) or t in MEM_TYPES) and p in CLOCK_PORTS:
                clock_bits.update(b for b in bits if isinstance(b, int))
    for pn, p in ports.items():
        if p['direction'] in ('input', 'inout'):
            for b in p['bits']:
                if isinstance(b, int):
                    driver[b] = ('<port>', pn)

    # the owner of each bit: the name its block is called by
    def prio(name):
        if name in ports:
            return 0 if ports[name]['direction'] != 'output' else 3
        if 'hdlname' not in nets[name]['attributes']:
            return 1                                    # module wire (or generate-block wire)
        return 2                                        # wire inside a flattened instance

    owner = {}
    for name, v in nets.items():
        inst = 'hdlname' in v['attributes'] and name not in ports
        for b in v['bits']:
            if not isinstance(b, int):
                continue
            if inst and b not in reg_bits:
                continue                                # e.g. a library flop's din: anonymous logic
            key = (prio(name), len(name), name)
            if b not in owner or key < owner[b][0]:
                owner[b] = (key, name)
    owner = {b: n for b, (k, n) in owner.items()}

    # an output that owns flip-flop bits gets a register block of its own
    synth = {}
    for pn, p in ports.items():
        if p['direction'] == 'output':
            for b in p['bits']:
                if owner.get(b) == pn and b in reg_bits:
                    owner[b] = synth.setdefault(pn, pn + '.q')

    def bits_of(name):
        if name in synth.values():
            pn = [k for k, v in synth.items() if v == name][0]
            return [b for b in ports[pn]['bits'] if owner.get(b) == name]
        return nets[name]['bits']

    names = sorted({n for n in owner.values()} | {p for p in ports})
    memo = {}

    def sources(b, stack=()):
        """named signals that bit b depends on, through anonymous logic"""
        if not isinstance(b, int):
            return set()
        if b in owner:
            return {owner[b]}
        if b in memo:
            return memo[b]
        if b in stack or b not in driver:
            return set()
        memo[b] = s = cell_sources(driver[b], b, stack + (b,))
        return s

    def cell_sources(drv, b, stack):
        cn, port = drv
        if cn == '<port>':
            return set()
        c = m['cells'][cn]
        if not c['type'].startswith('$'):
            return {cn}                                  # a submodule kept as a block
        dirs = c.get('port_directions', {})
        s = set()
        reg = is_reg(c['type']) or c['type'] in MEM_TYPES
        idx = c['connections'][port].index(b)
        for p, bits in c['connections'].items():
            if dirs.get(p) != 'input' or (reg and p in CLOCK_PORTS):
                continue
            if reg and p == 'D' and len(bits) == len(c['connections'][port]):
                bits = [bits[idx]]                       # D[i] -> Q[i]
            for x in bits:
                s |= sources(x, stack)
        return s

    nodes = []
    for name in names:
        bits = bits_of(name)
        own = [b for b in bits if isinstance(b, int) and owner.get(b) == name]
        if name in ports and ports[name]['direction'] in ('input', 'inout'):
            kind = 'input'
        elif name in ports and ports[name]['direction'] == 'output':
            kind = 'output'
        elif own and sum(b in reg_bits for b in own) * 2 >= len(own):
            kind = 'reg'
        else:
            kind = 'comb'
        fanin = set()
        if kind != 'input':
            for b in bits:
                if not isinstance(b, int):
                    continue
                if owner.get(b) not in (None, name):
                    fanin.add(owner[b])                  # alias of another signal
                elif b in driver:
                    fanin |= cell_sources(driver[b], b, (b,))
        fanin.discard(name)
        if kind in ('comb', 'reg') and not fanin:
            continue                                     # constant
        src = (nets.get(name) or nets.get(name[:-2]) or {}).get('attributes', {}).get('src', '')
        nodes.append(dict(id=name, kind=kind, width=len(bits), src=src, fanin=sorted(fanin),
                          clock=any(b in clock_bits for b in bits if isinstance(b, int)),
                          vcd=name if name not in synth.values() else name[:-2]))
    for cn, c in m['cells'].items():
        if c['type'].startswith('$'):
            continue
        dirs = c.get('port_directions', {})
        fanin = set()
        for p, bits in c['connections'].items():
            if dirs.get(p) != 'output':
                for b in bits:
                    fanin |= sources(b)
        src = c.get('attributes', {}).get('src', '')
        nodes.append(dict(id=cn, kind='inst', module=c['type'].lstrip(chr(92)), width=0, src=src,
                          fanin=sorted(fanin - {cn}), clock=False, vcd=None))
    keep = {n['id'] for n in nodes}
    for n in nodes:
        n['fanin'] = [f for f in n['fanin'] if f in keep]

    # declaration order (file, line) gives a sensible first ordering
    def line(n):
        mm = re.search(r'(.*):(\d+)', n['src'].split('|')[0])
        return (mm.group(1), int(mm.group(2))) if mm else ('~', 0)
    nodes.sort(key=line)

    hidden = [n['id'] for n in nodes if n['clock'] or (n['kind'] == 'input' and re.match(RESET_RE, n['id']))
              or any(re.search(h, n['id']) for h in hide)]
    return nodes, hidden


# ------------------------------------------------------------------ VCD
def norm(path):
    """tb.dut.ld_cmp(0).ovl and tb.dut.ld_cmp[0].ovl -> the same key"""
    return re.sub(r'\((\d+)\)', r'[\1]', path.replace('\\', ''))


def read_vcd(fn, want, scope, clock, negedge):
    """want: list of signal paths relative to the DUT scope.
    Returns (scope, cycles, {path: [value string per cycle]})."""
    vars_ = {}                  # id -> list of (path, bit index or None, width)
    stack, defs = [], True
    paths = {}                  # path -> list of (id, bit or None, width)
    f = open(fn, encoding='utf-8', errors='replace')
    toks = iter_tokens(f)
    for t in toks:
        if t == '$scope':
            next(toks)
            stack.append(next(toks))
        elif t == '$upscope':
            stack.pop()
        elif t == '$var':
            v = []
            for x in toks:
                if x == '$end':
                    break
                v.append(x)
            typ, width, ident, name = v[0], int(v[1]), v[2], v[3]
            rng = ''.join(v[4:])
            mm = re.fullmatch(r'(.*?)\[(\d+)\]', name + rng) if (rng or '[' in name) else None
            bit = None
            if mm and width == 1 and not re.fullmatch(r'\[\d+:\d+\]', rng):
                name, bit = mm.group(1), int(mm.group(2))
            path = norm('.'.join(stack + [name]))
            paths.setdefault(path, []).append((ident, bit, width))
        elif t == '$enddefinitions':
            next(toks)
            break

    if scope is None:            # the scope that has most of the wanted signals
        best = (0, '')
        scopes = {p.rsplit('.', 1)[0] for p in paths}
        for s in scopes:
            hits = sum((s + '.' + norm(w)) in paths for w in want)
            best = max(best, (hits, s))
        scope = best[1]
    scope = norm(scope)
    sigs = {}
    for w in want:
        p = scope + '.' + norm(w)
        if p in paths:
            sigs[w] = paths[p]
    if clock not in sigs:
        sys.exit('rtlflow: clock %s not found in scope %s of %s' % (clock, scope, fn))
    ids = {i for lst in sigs.values() for i, _, _ in lst}
    cur = {i: 'x' for i in ids}
    cid = sigs[clock][0][0]
    edge = '0' if negedge else '1'

    def value(w):
        lst = sigs[w]
        if len(lst) == 1 and lst[0][1] is None:
            i, _, width = lst[0]
            v = cur[i]
            return v.rjust(width, v[0] if v[0] in 'xz' else '0')[-width:]
        bits = sorted(((b, cur[i][-1]) for i, b, _ in lst), reverse=True)
        return ''.join(v for _, v in bits)

    samples, times, t, pend, rose = [], [], 0, [], False

    def flush(t_next):
        nonlocal pend, rose
        if rose:                                         # sample before the edge's changes
            samples.append({w: value(w) for w in sigs})
            times.append(t_next)
        for i, v in pend:
            cur[i] = v
        pend, rose = [], False

    tnow = 0
    for tok in toks:
        c = tok[0]
        if c == '#':
            flush(tnow)
            tnow = int(tok[1:])
        elif c in '01xzXZ' and len(tok) > 1:
            i = tok[1:]
            if i in ids:
                v = tok[0].lower()
                if i == cid and v == edge and cur[cid][-1] != edge:
                    rose = True
                pend.append((i, v))
        elif c in 'bBrR':
            v, i = tok[1:].lower(), next(toks)
            if i in ids:
                if c in 'rR':
                    v = 'x'
                if i == cid and v[-1] == edge and cur[cid][-1] != edge:
                    rose = True
                pend.append((i, v))
    flush(tnow)
    f.close()
    # samples[k] is the state just before edge k, i.e. of the cycle that started
    # at edge k-1; that cycle is called k-1 (the one before the first edge is dropped)
    cycles = [dict(label=str(k - 1), t=times[k - 1]) for k in range(1, len(samples))]
    vals = {w: [samples[k][w] for k in range(1, len(samples))] for w in sigs}
    return scope, cycles, vals


def iter_tokens(f):
    for line in f:
        for t in line.split():
            yield t


def read_trace(fn, want):
    cycles, vals = [], {w: [] for w in want}
    for ln in open(fn, encoding='utf-8'):
        kv = dict(re.findall(r'([\w.\[\]$]+)=(\S+)', ln))
        if not kv:
            continue
        cycles.append(dict(label=kv.get('cyc', str(len(cycles))), t=None))
        for w in want:
            vals[w].append(kv.get(w))
    return cycles, {w: v for w, v in vals.items() if any(x is not None for x in v)}


def to_hex(bits, width):
    """'0101x...' (MSB first) -> hex string; a digit with an x/z bit is 'x'/'z'"""
    if bits is None:
        return None
    bits = bits.rjust(width, '0')[-width:]
    pad = (-len(bits)) % 4
    bits = '0' * pad + bits
    out = []
    for k in range(0, len(bits), 4):
        q = bits[k:k + 4]
        out.append('x' if 'x' in q else 'z' if 'z' in q else '%x' % int(q, 2))
    return ''.join(out)


def trace_hex(v, width):
    if v is None:
        return None
    v = v.lower()
    n = (width + 3) // 4
    if re.fullmatch(r'[xz]+', v):
        return v[0] * n
    return v.rjust(n, '0')[-n:]


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='+')
    ap.add_argument('--top', required=True)
    ap.add_argument('-I', dest='incdirs', action='append', default=[])
    ap.add_argument('-D', dest='defines', action='append', default=[])
    ap.add_argument('--sv', action='store_true')
    ap.add_argument('--param', action='append', default=[])
    ap.add_argument('--lib', action='append', default=[])
    ap.add_argument('--blackbox', action='append', default=[])
    ap.add_argument('--vcd')
    ap.add_argument('--trace')
    ap.add_argument('--scope')
    ap.add_argument('--clock')
    ap.add_argument('--negedge', action='store_true')
    ap.add_argument('--cycles')
    ap.add_argument('--hide', action='append', default=[])
    ap.add_argument('--only', action='append', default=[])
    ap.add_argument('--layout')
    ap.add_argument('--title')
    ap.add_argument('-o', '--out')
    a = ap.parse_args()

    yj = run_yosys(a.files, a.top, a.incdirs, a.defines, a.sv, a.param, a.lib, a.blackbox)
    if a.top not in yj['modules']:
        sys.exit('rtlflow: module %s not found' % a.top)
    nodes, hidden = build_graph(yj, a.top, a.hide)
    base_hidden = list(hidden)
    if a.only:
        hidden = sorted(set(hidden) | {n['id'] for n in nodes if not any(re.search(o, n['id']) for o in a.only)})
    clocks = [n['id'] for n in nodes if n['clock'] and n['kind'] == 'input']
    clock = a.clock or (clocks[0] if clocks else None)
    kinds = {}
    for n in nodes:
        kinds[n['kind']] = kinds.get(n['kind'], 0) + 1
    print('%s: %s, %d edges; hidden: %s' % (a.top, ', '.join('%d %s' % (v, k) for k, v in kinds.items()),
                                             sum(len(n['fanin']) for n in nodes),
                                             ', '.join(hidden) if len(hidden) < 12 else '%d blocks' % len(hidden)))

    cycles, values, scope = [], {}, None
    want = {n['id']: n['vcd'] for n in nodes if n['vcd']}
    if a.vcd:
        if not clock:
            sys.exit('rtlflow: no clock found, give --clock')
        scope, cycles, raw = read_vcd(a.vcd, sorted(set(want.values()) | {clock}), a.scope, clock, a.negedge)
        for n in nodes:
            if n['vcd'] in raw:
                values[n['id']] = [to_hex(v, n['width']) for v in raw[n['vcd']]]
    elif a.trace:
        cycles, raw = read_trace(a.trace, sorted(set(want.values())))
        for n in nodes:
            if n['vcd'] in raw:
                values[n['id']] = [trace_hex(v, n['width']) for v in raw[n['vcd']]]
    if a.cycles:
        lo, hi = (a.cycles.split(':') + [''])[:2]
        sl = slice(int(lo) if lo else None, int(hi) if hi else None)
        cycles = cycles[sl]
        values = {k: v[sl] for k, v in values.items()}
    if cycles:
        miss = [n['id'] for n in nodes if n['id'] not in values and n['id'] not in hidden and n['kind'] != 'inst']
        print('%d cycles%s; no values for: %s' % (len(cycles), ' from scope ' + scope if scope else '',
                                                   ', '.join(miss) or '-'))

    layout = None
    if a.layout:
        with open(a.layout, encoding='utf-8') as f:
            layout = json.load(f)
    for n in nodes:
        del n['vcd']
    data = dict(module=a.top, title=a.title or a.top, files=[os.path.basename(f) for f in a.files],
                nodes=nodes, hidden=hidden, base_hidden=base_hidden, cycles=cycles, values=values, layout=layout,
                source=a.vcd and os.path.basename(a.vcd) or a.trace and os.path.basename(a.trace) or '')
    with open(os.path.join(HERE, 'viewer.html'), encoding='utf-8') as f:
        page = f.read()
    page = page.replace('/*RTLFLOW_DATA*/null', json.dumps(data, separators=(',', ':')))
    out = a.out or a.top + '.html'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(page)
    print('wrote %s (%.0f kB)' % (out, os.path.getsize(out) / 1e3))


if __name__ == '__main__':
    main()
