# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 whensungoesdown <whensungoes@gmail.com>
"""Screenshot of a generated page, e.g. for the README.

  python tests/screenshot.py PAGE.html OUT.png [CYCLE.STEP] [WIDTHxHEIGHT]

CYCLE.STEP is the step to show (default 16.1, cycle 16, signals);
the default size is 1600x900.
"""
import os
import sys

from playwright.sync_api import sync_playwright

page_file, out = os.path.abspath(sys.argv[1]), sys.argv[2]
step = sys.argv[3] if len(sys.argv) > 3 else '16.1'
w, h = map(int, (sys.argv[4] if len(sys.argv) > 4 else '1600x900').split('x'))
url = 'file:///' + page_file.replace(os.sep, '/').lstrip('/') + '#' + step
with sync_playwright() as p:
    try:
        b = p.chromium.launch(channel='msedge')
    except Exception:
        b = p.chromium.launch(channel='chrome')
    pg = b.new_page(viewport={'width': w, 'height': h}, device_scale_factor=1)
    pg.goto(url)
    pg.wait_for_timeout(1500)
    pg.screenshot(path=out)
    pg.evaluate('localStorage.clear()')
    b.close()
print('wrote', out)
