# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 whensungoesdown <whensungoes@gmail.com>
"""Check the logic of the blocks against the dump.

  python tests/logic_test.py PAGE.html [BLOCK]

For every block with logic and every cycle, the page evaluates the logic from
the values of its inputs and compares it with the dump: a comb block with
its value in the cycle, a register with its value in the next cycle. Prints
the counts and the first mismatches; with BLOCK, also the logic panel text.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

page_file = os.path.abspath(sys.argv[1])
url = 'file:///' + page_file.replace(os.sep, '/').lstrip('/')
with sync_playwright() as p:
    b = p.chromium.launch(channel='msedge')
    pg = b.new_page(viewport={'width': 1800, 'height': 1150})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(url)
    pg.wait_for_timeout(1500)
    r = pg.evaluate("""() => {
      let ok = 0, bad = 0, unk = 0; const miss = [];
      for (const n of D.nodes) {
        if (!n.expr) continue;
        for (let c = 0; c < NC; c++) {
          const want = n.kind === 'reg' ? (c + 1 < NC ? val(n.id, c + 1) : null) : val(n.id, c);
          if (want == null || /[xz]/.test(want)) continue;
          const got = evHex(n.expr, c);
          if (/x/.test(got)) { unk++; continue; }
          if (hexVal(got, n.width).v === hexVal(want, n.width).v) ok++;
          else { bad++; if (miss.length < 8) miss.push(`${n.id} cycle ${D.cycles[c].label}: logic ${got}, dump ${want}`); }
        }
      }
      return { ok, bad, unk, miss };
    }""")
    print('logic = dump: %d, different: %d, unknown: %d' % (r['ok'], r['bad'], r['unk']))
    for m in r['miss']:
        print('  ', m)
    if len(sys.argv) > 2:
        pg.evaluate('id => { sel = id; update(false); }', sys.argv[2])
        pg.wait_for_timeout(200)
        print(pg.inner_text('#info'))
        pg.locator('#side').screenshot(path=os.path.join(os.path.dirname(page_file), '_logic.png'))
    pg.evaluate('localStorage.clear()')
    print('errors:', errs or 'none')
    b.close()
