"""Check the value search of the side panel.

  python tests/search_test.py PAGE.html BLOCK QUERY [QUERY ...]

For each query: find forward twice, then backward once, and print the
cycles found and the message. Also checks the query parser on a few inputs.
"""
import os
import sys

from playwright.sync_api import sync_playwright

page_file, block, queries = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3:]
url = 'file:///' + page_file.replace(os.sep, '/').lstrip('/')
with sync_playwright() as p:
    b = p.chromium.launch(channel='msedge')
    pg = b.new_page(viewport={'width': 1800, 'height': 1150})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(url)
    pg.wait_for_timeout(1500)
    pg.evaluate('id => { sel = id; update(false); }', block)
    for q in queries:
        pg.evaluate('go(0, false)')
        pg.fill('#vq', q)
        found = []
        for key in ('Enter', 'Enter', 'Shift+Enter'):
            pg.press('#vq', key)
            pg.wait_for_timeout(100)
            found.append(pg.evaluate('D.cycles[cur.c].label'))
            msg = pg.inner_text('#vres')
            # the value at the cycle found, for a check by eye
            v = pg.evaluate('id => val(id, cur.c)', block)
        print('%-14s -> cycles %s, value there %s | %s' % (q, found, v, msg))
        print('   focus kept in the box:', pg.evaluate("document.activeElement.id") == 'vq')
    for q, w in [('70000000', 32), ("32'h7000_0000", 32), ('0b1', 1), ("4'b01?1", 4), ('0d16', 8),
                 ('b0', 8), ('1ff', 8), ('zz', 8), ('g', 8)]:
        r = pg.evaluate('([q, w]) => { const r = parseQuery(q, w); return typeof r === "string" ? r : r.source; }', [q, w])
        print('parse %-14s w=%-2d -> %s' % (q, w, r))
    pg.evaluate('localStorage.clear()')
    print('errors:', errs or 'none')
    b.close()
