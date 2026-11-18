# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 whensungoesdown <whensungoes@gmail.com>
"""Check Focus and "next change" on a generated page.

  python tests/focus_test.py PAGE.html BLOCK OUTPREFIX
"""
import os
import sys

from playwright.sync_api import sync_playwright

page_file, block, out = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3]
url = 'file:///' + page_file.replace(os.sep, '/').lstrip('/')
with sync_playwright() as p:
    b = p.chromium.launch(channel='msedge')
    pg = b.new_page(viewport={'width': 1800, 'height': 1150})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(url)
    pg.wait_for_timeout(1500)
    pg.evaluate('id => { sel = id; update(false); }', block)
    pg.select_option('#focn', '2')
    pg.click('#focbtn')
    pg.wait_for_timeout(500)
    print('visible blocks after focus:', pg.evaluate('G.nodes.length'), 'of', pg.evaluate('D.nodes.length'))
    pg.click('#nchg')
    pg.wait_for_timeout(300)
    print('next change of %s at cycle %s' % (block, pg.evaluate('D.cycles[cur.c].label')))
    pg.keyboard.press('ArrowLeft')           # the next-state step of the cycle before
    pg.wait_for_timeout(1200)
    pg.screenshot(path=out + '_focus_next.png')
    pg.keyboard.press('ArrowRight')
    pg.wait_for_timeout(400)
    pg.screenshot(path=out + '_focus_edge.png')
    pg.select_option('#hid', '*')
    pg.wait_for_timeout(500)
    print('after show all:', pg.evaluate('G.nodes.length'))
    pg.fill('#cyc', '100')
    pg.press('#cyc', 'Enter')
    print('go to cycle 100 ->', pg.evaluate('D.cycles[cur.c].label'))
    pg.evaluate('localStorage.clear()')
    print('errors:', errs or 'none')
    b.close()
