# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 whensungoesdown <whensungoes@gmail.com>
"""rtlflow: show a synchronous Verilog module as a top-to-bottom block diagram
and step through a simulation of it, cycle by cycle, in a web page.

  inputs (top)  ->  registers  ->  logic  ->  outputs (bottom)

The diagram is generated from the Verilog with Yosys: every named signal of
the module becomes a block, the anonymous logic between named signals is
collapsed into the edges. The values come from a VCD file (or a text trace),
sampled once per clock cycle.

usage:
  python rtlflow.py FILE.v [FILE.v ...] --top MODULE [--vcd SIM.vcd] [-o OUT.html]

  -f FLIST                   read files, +incdir+ and +define+ from a simulator file list
                             (repeatable; nested -f, ${PROJECT_ROOT} = parent of the flist's dir)
  --skip REGEX               leave out flist files whose path matches, e.g. altera_mf
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


def read_flist(fn, files, incdirs, defines, skip, seen=None):
    """expand a simulator file list (vlog/vcs/xrun style) into files, include
    directories and defines.

    - # and // start a comment
    - ${PROJECT_ROOT} / $PROJECT_ROOT is the parent of the flist's directory
      (as soc2's simulate.sh sets it); other ${VAR} / $VAR come from the
      environment
    - +incdir+DIR[+DIR...], +define+NAME[=VAL][+...], -f / -F nested flist,
      -v FILE (library file); other options are ignored
    - relative paths are relative to the flist's directory
    """
    seen = seen if seen is not None else set()
    fn = os.path.abspath(fn)
    if fn in seen:
        return
    seen.add(fn)
    here = os.path.dirname(fn)
    env = dict(os.environ, PROJECT_ROOT=os.path.dirname(here))

    def sub(t):
        t = re.sub(r'\$\{(\w+)\}|\$(\w+)', lambda m: env.get(m.group(1) or m.group(2), m.group(0)), t)
        return t if os.path.isabs(t) else os.path.normpath(os.path.join(here, t))

    with open(fn, encoding='utf-8', errors='replace') as f:
        toks = []
        for line in f:
            line = re.sub(r'(#|//).*', '', line).strip()
            toks += line.split()
    it = iter(toks)
    for t in it:
        if t.startswith('+incdir+'):
            incdirs += [sub(d) for d in t[8:].split('+') if d]
        elif t.startswith('+define+'):
            defines += [d for d in t[8:].split('+') if d]
        elif t in ('-f', '-F'):
            read_flist(sub(next(it)), files, incdirs, defines, skip, seen)
        elif t == '-v':
            files.append(sub(next(it)))
        elif t in ('-y', '-work', '-L'):
            next(it, None)
        elif t.startswith(('-', '+')):
            continue
        else:
            f = sub(t)
            if any(re.search(x, f.replace(os.sep, '/')) for x in skip):
                continue
            if not os.path.exists(f):
                print('rtlflow: %s: not found: %s' % (os.path.basename(fn), f), file=sys.stderr)
                continue
            files.append(f)


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

    # the logic of each block as an expression over the named signals: the
    # anonymous cells between named signals are expanded, named signals are leaves
    exprs_of(m, nodes, keep, owner, driver, bits_of, reg_bits)

    # declaration order (file, line) gives a sensible first ordering
    def line(n):
        mm = re.search(r'(.*):(\d+)', n['src'].split('|')[0])
        return (mm.group(1), int(mm.group(2))) if mm else ('~', 0)
    nodes.sort(key=line)

    hidden = [n['id'] for n in nodes if n['clock'] or (n['kind'] == 'input' and re.match(RESET_RE, n['id']))
              or any(re.search(h, n['id']) for h in hide)]
    return nodes, hidden


EXPR_MAX = 400          # nodes per expression; a bigger one ends in '...'
BIN_OPS = {'$and', '$or', '$xor', '$xnor', '$logic_and', '$logic_or', '$eq', '$ne', '$eqx', '$nex', '$lt', '$le',
           '$gt', '$ge', '$add', '$sub', '$mul', '$div', '$mod', '$shl', '$shr', '$sshl', '$sshr', '$shift', '$shiftx'}
UN_OPS = {'$not', '$neg', '$logic_not', '$reduce_and', '$reduce_or', '$reduce_xor', '$reduce_xnor', '$reduce_bool'}


def pbits(v):
    """a Yosys parameter as a bit string, MSB first"""
    return v if isinstance(v, str) and re.fullmatch(r'[01xz]+', v) else bin(int(v))[2:]


def exprs_of(m, nodes, keep, owner, driver, bits_of, reg_bits):
    """sets n['expr'] (value of a comb block / output) and, for a register, the
    next value it loads at the clock edge. Trees with short keys:
      {o:'s', n:name, l:lo, w}      bits lo..lo+w-1 of a named signal
      {o:'k', v:'01x..', w}         constant, MSB first
      {o:'{}', a:[msb..lsb], w}     concatenation
      {o:'[]', a:[e], l:lo, w}      bits of an expression
      {o:'i', n:'inst.port', w}     output of a submodule block (no value)
      {o:'mux', a:[sel, then, else], w, as:1 if an asynchronous reset}
      {o:'pmux', a:[default, sel0, case0, sel1, case1, ...], w}
      {o:op, a:[...], w, s:1 if signed}   $and -> 'and', ...
      {o:'...', w}                  not expanded (too big, a loop, memory)
    """
    cells = m['cells']
    drv_i = {}
    for cn, c in cells.items():
        dirs = c.get('port_directions', {})
        for p, bits in c['connections'].items():
            if dirs.get(p) == 'output':
                for i, b in enumerate(bits):
                    if isinstance(b, int):
                        drv_i[b] = i
    # flattened instances ($scopeinfo cells, flatten keeps them): their module and port nets,
    # to name the pins of a library flip-flop (dffe_ns.en, dffrl_ns.rst_l, ...)
    scopes = {cn: c.get('attributes', {}) for cn, c in cells.items() if c['type'] == '$scopeinfo'}
    inst_ports = {}
    for nn, v in m['netnames'].items():
        hd = v.get('attributes', {}).get('hdlname')
        if hd and ' ' in hd:
            parts = hd.split(' ')
            inst_ports.setdefault('.'.join(parts[:-1]), {})[parts[-1]] = tuple(v['bits'])

    def inst_of(cn):                                    # $flatten\a.\b.$procdff$12 -> a.b
        if '$flatten' not in cn:
            return None
        path = cn.replace('$flatten', '').replace(chr(92), '').rsplit('.$', 1)[0]
        return path if path in scopes else None

    def pin_of(inst, bits):
        for port, pb in inst_ports.get(inst, {}).items():
            if pb == tuple(bits):
                return port
        return None

    own_i, width = {}, {}
    for n in nodes:
        if n['kind'] == 'inst':
            continue
        bits = bits_of(n['id'])
        width[n['id']] = len(bits)
        for i, b in enumerate(bits):
            if owner.get(b) == n['id']:
                own_i[b] = i

    for n in nodes:
        if n['kind'] in ('input', 'inst'):
            continue
        budget = [EXPR_MAX]
        name = n['id']

        def new(d):
            budget[0] -= 1
            return d

        def sig(bits, depth, top=False):
            segs = []                                   # [kind, key, first index, count, const bits]
            for b in bits:
                if not isinstance(b, int):
                    k = ('c', None, 0)
                elif b in owner and owner[b] in keep and not (top and owner[b] == name):
                    k = ('s', owner[b], own_i.get(b, 0))
                elif b in driver and driver[b][0] != '<port>':
                    k = ('d', driver[b], drv_i.get(b, 0))
                else:
                    k = ('c', None, 0)
                    b = 'x'
                last = segs[-1] if segs else None
                if last and last[0] == k[0] and last[1] == k[1] and (k[0] == 'c' or k[2] == last[2] + last[3]):
                    last[3] += 1
                    last[4].append(b)
                else:
                    segs.append([k[0], k[1], k[2], 1, [b]])
            out = []
            for kind, key, lo, cnt, cb in segs:
                if budget[0] <= 0 or depth > 40:
                    out.append({'o': '...', 'w': cnt})
                elif kind == 'c':
                    out.append(new({'o': 'k', 'v': ''.join(str(x) for x in reversed(cb)), 'w': cnt}))
                elif kind == 's':
                    out.append(new({'o': 's', 'n': key, 'l': lo, 'w': cnt}))
                else:
                    cn, port = key
                    e = cell(cn, port, depth + 1)
                    pw = len(cells[cn]['connections'][port])
                    if lo or cnt != pw:
                        e = new({'o': '[]', 'a': [e], 'l': lo, 'w': cnt})
                    out.append(e)
            if len(out) == 1:
                return out[0]
            return new({'o': '{}', 'a': out[::-1], 'w': len(bits)})

        def cell(cn, port, depth):
            c = cells[cn]
            t, conn, prm = c['type'], c['connections'], c.get('parameters', {})
            w = len(conn[port])
            if not t.startswith('$'):
                return new({'o': 'i', 'n': cn + '.' + port, 'w': w})
            signed = all(int(pbits(prm.get(k, '0')), 2) for k in ('A_SIGNED', 'B_SIGNED') if k in prm)
            if t in BIN_OPS:
                e = {'o': t[1:], 'a': [sig(conn['A'], depth), sig(conn['B'], depth)], 'w': w}
            elif t in UN_OPS:
                e = {'o': t[1:], 'a': [sig(conn['A'], depth)], 'w': w}
            elif t == '$pos':
                return sig(conn['A'], depth)
            elif t == '$mux':
                e = {'o': 'mux', 'a': [sig(conn['S'], depth), sig(conn['B'], depth), sig(conn['A'], depth)], 'w': w}
            elif t == '$pmux':
                a = [sig(conn['A'], depth)]
                for i, sb in enumerate(conn['S']):
                    a += [sig([sb], depth), sig(conn['B'][i * w:(i + 1) * w], depth)]
                e = {'o': 'pmux', 'a': a, 'w': w}
            else:
                return new({'o': '...', 'w': w, 't': t[1:]})
            if signed and e['o'] in ('lt', 'le', 'gt', 'ge', 'sshr', 'div', 'mod', 'mul', 'neg'):
                e['s'] = 1
            return new(e)

        def pol(bits, p):
            e = sig(bits, 1)
            return e if int(pbits(p), 2) else new({'o': 'logic_not', 'a': [e], 'w': 1})

        def const(p, lo, cnt):
            v = pbits(p)[::-1].ljust(lo + cnt, '0')
            return new({'o': 'k', 'v': v[lo:lo + cnt][::-1], 'w': cnt})

        def is_reset_sel(sbits, pin):
            if pin and re.match(RESET_RE, pin):
                return True
            names = {owner.get(b) for b in sbits}
            return len(names) == 1 and None not in names and bool(re.match(RESET_RE, names.pop()))

        def chain(dbits, qbits, inst, depth):
            # the muxes at the D input: one arm the register's own Q is an enable (the
            # register holds), one arm a constant with a reset as select is a reset.
            # Tagged with role, the library pin (if the select is one) and k: 1 if
            # the special arm (hold / reset value) is the 'then' arm, 0 if the 'else' arm.
            d0 = dbits[0] if dbits else None
            drv = driver.get(d0) if isinstance(d0, int) else None
            if depth > 8 or not drv or drv[0] == '<port>' or cells[drv[0]]['type'] != '$mux' or drv[1] != 'Y':
                return sig(dbits, 1)
            i0 = drv_i[d0]
            if any(driver.get(b) != drv or drv_i.get(b) != i0 + i for i, b in enumerate(dbits)):
                return sig(dbits, 1)
            conn = cells[drv[0]]['connections']
            A, B, S = conn['A'][i0:i0 + len(dbits)], conn['B'][i0:i0 + len(dbits)], conn['S']
            pin = pin_of(inst, S) if inst else None
            const_arm = lambda x: all(not isinstance(b, int) for b in x)
            if A == qbits or B == qbits:
                k = 1 if B == qbits else 0
                data = chain(A if k else B, qbits, inst, depth + 1)
                hold = sig(qbits, 1)
                arms = [hold, data] if k else [data, hold]
                return new({'o': 'mux', 'a': [sig(S, 1)] + arms, 'w': len(dbits), 'role': 'en', 'pin': pin, 'k': k})
            if (const_arm(A) or const_arm(B)) and is_reset_sel(S, pin):
                k = 1 if const_arm(B) else 0
                data = chain(A if k else B, qbits, inst, depth + 1)
                rst = sig(B if k else A, 1)
                arms = [rst, data] if k else [data, rst]
                return new({'o': 'mux', 'a': [sig(S, 1)] + arms, 'w': len(dbits), 'role': 'srst', 'pin': pin, 'k': k})
            return sig(dbits, 1)

        def next_value(cn, lo, cnt):
            c = cells[cn]
            t, conn, prm = c['type'], c['connections'], c.get('parameters', {})
            if 'D' not in conn:
                return new({'o': '...', 'w': cnt, 't': t[1:]})
            qb = conn['Q'][lo:lo + cnt]
            e = chain(conn['D'][lo:lo + cnt], qb, inst_of(cn), 0)
            q = sig(qb, 1)
            if 'EN' in conn:
                e = new({'o': 'mux', 'a': [pol(conn['EN'], prm.get('EN_POLARITY', '1')), e, q], 'w': cnt,
                         'role': 'en', 'pin': 'EN', 'k': 0})
            if 'SRST' in conn:
                e = new({'o': 'mux', 'a': [pol(conn['SRST'], prm.get('SRST_POLARITY', '1')),
                                          const(prm.get('SRST_VALUE', '0'), lo, cnt), e], 'w': cnt,
                         'role': 'srst', 'pin': 'SRST', 'k': 1})
            if 'ARST' in conn:
                e = new({'o': 'mux', 'a': [pol(conn['ARST'], prm.get('ARST_POLARITY', '1')),
                                          const(prm.get('ARST_VALUE', '0'), lo, cnt), e], 'w': cnt, 'as': 1,
                         'role': 'arst', 'pin': 'ARST', 'k': 1})
            return e

        def ff_info(cn):
            c = cells[cn]
            conn, prm = c['connections'], c.get('parameters', {})
            inst = inst_of(cn)
            clk = owner.get(conn['CLK'][0]) if 'CLK' in conn and isinstance(conn['CLK'][0], int) else None
            return {'cell': c['type'][1:], 'inst': inst,
                    'module': scopes[inst].get('module_hdlname') if inst else None,
                    'clk': clk, 'edge': 'neg' if 'CLK_POLARITY' in prm and not int(pbits(prm['CLK_POLARITY']), 2) else 'pos'}

        bits = bits_of(name)
        if n['kind'] == 'reg':
            parts = []                                  # [cell, first Q index, count]
            for b in bits:
                d = driver.get(b) if isinstance(b, int) and b in reg_bits else None
                if d is None:
                    parts.append(['', 0, 1])
                    continue
                last = parts[-1] if parts else None
                if last and last[0] == d[0] and drv_i[b] == last[1] + last[2]:
                    last[2] += 1
                else:
                    parts.append([d[0], drv_i[b], 1])
            out = [next_value(cn, lo, cnt) if cn else {'o': '...', 'w': cnt} for cn, lo, cnt in parts]
            n['expr'] = out[0] if len(out) == 1 else {'o': '{}', 'a': out[::-1], 'w': len(bits)}
            cn0 = [cn for cn, lo, cnt in parts if cn]
            if cn0:
                n['ff'] = dict(ff_info(cn0[0]), parts=len(set(cn0)))
        else:
            n['expr'] = sig(bits, 0, top=True)

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
    ap.add_argument('files', nargs='*')
    ap.add_argument('-f', dest='flists', action='append', default=[])
    ap.add_argument('--skip', action='append', default=[])
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

    for fl in a.flists:
        read_flist(fl, a.files, a.incdirs, a.defines, a.skip)
    a.files = list(dict.fromkeys(a.files))
    if not a.files:
        sys.exit('rtlflow: no Verilog files (give files or -f FLIST)')
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
