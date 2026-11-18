# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 whensungoesdown <whensungoes@gmail.com>
"""Smoke test of a generated rtlflow page in a real browser (Edge or Chrome via Playwright).

  python tests/browser_test.py PAGE.html OUTPREFIX

Writes screenshots OUTPREFIX_*.png and the downloaded layout OUTPREFIX_layout.json,
prints the checks and any JavaScript errors.
"""
import os
import sys

from playwright.sync_api import sync_playwright

page_file, out = os.path.abspath(sys.argv[1]), sys.argv[2]
url = 'file:///' + page_file.replace(os.sep, '/').lstrip('/')

with sync_playwright() as p:
    try:
        b = p.chromium.launch(channel='msedge')
    except Exception:
        b = p.chromium.launch(channel='chrome')
    pg = b.new_page(viewport={'width': 1800, 'height': 1150}, accept_downloads=True)
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.on('console', lambda m: m.type == 'error' and errs.append(m.text))
    pg.goto(url + '#16.1')
    pg.wait_for_timeout(1500)
    pg.screenshot(path=out + '_signals.png')
    pg.keyboard.press('ArrowRight')
    pg.wait_for_timeout(1200)
    pg.screenshot(path=out + '_next.png')
    pg.select_option('#lit', 'bit')
    pg.wait_for_timeout(300)
    pg.screenshot(path=out + '_bit.png')
    pg.select_option('#lit', 'nz')

    # drag the first block 200 px to the right
    box = pg.locator('g.node').nth(0).bounding_box()
    pg.mouse.move(box['x'] + 20, box['y'] + 10)
    pg.mouse.down()
    pg.mouse.move(box['x'] + 120, box['y'] + 10, steps=5)
    pg.mouse.move(box['x'] + 220, box['y'] + 10, steps=5)
    pg.mouse.up()
    pg.wait_for_timeout(500)
    lay1 = pg.evaluate('JSON.stringify(layoutJSON().pos)')

    # select a block and hide it
    pg.locator('g.node').nth(5).click()
    pg.wait_for_timeout(200)
    name = pg.evaluate('sel')
    pg.click('#hidebtn')
    pg.wait_for_timeout(300)
    hid = pg.evaluate('[...hidden]')

    pg.reload()
    pg.wait_for_timeout(1200)
    lay2 = pg.evaluate('JSON.stringify(layoutJSON().pos)')
    hid2 = pg.evaluate('[...hidden]')
    with pg.expect_download() as dl:
        pg.click('#save')
    dl.value.save_as(out + '_layout.json')
    pg.select_option('#hid', name)
    pg.wait_for_timeout(300)
    print('hid %s: hidden %s; after reload %s; shown again -> %s' % (name, hid, hid2, pg.evaluate('[...hidden]')))
    print('layout kept after reload:', lay1 == lay2)
    pg.click('#auto')
    pg.wait_for_timeout(300)
    pg.evaluate('localStorage.clear()')
    print('errors:', errs or 'none')
    b.close()
