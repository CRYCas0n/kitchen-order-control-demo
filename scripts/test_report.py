"""Capture actual unittest output and take a screenshot of the resulting report."""
import html
import io
import unittest

from playwright.sync_api import sync_playwright

from app.config import ROOT

stream=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
output=stream.getvalue()
artifacts=ROOT/'artifacts';artifacts.mkdir(exist_ok=True)
(artifacts/'automated-tests.txt').write_text(output,encoding='utf-8')
report=artifacts/'automated-tests.html'
report.write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Automated test results</title>'
                 '<style>body{font:15px system-ui;background:#f5f7f5;color:#22342e;padding:35px}h1{color:#176c50}pre{font:13px/1.7 monospace;white-space:pre-wrap;background:white;padding:25px;border:1px solid #dfe7e1;border-radius:10px}</style>'
                 f'<h1>{result.testsRun} automated tests · {"PASS" if result.wasSuccessful() else "FAIL"}</h1>'
                 '<p>Kitchen Control · 30.09.2026 · actual unittest output · isolated SQLite / mocked Telegram transport</p>'
                 f'<pre>{html.escape(output)}</pre></html>',encoding='utf-8')
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    page=browser.new_page(viewport={'width':1440,'height':1100});page.goto(report.as_uri())
    page.screenshot(path=str(artifacts/'20-automated-tests.png'),full_page=True);browser.close()
print(f'{result.testsRun} tests: {"PASS" if result.wasSuccessful() else "FAIL"}; report and screenshot saved')
raise SystemExit(0 if result.wasSuccessful() else 1)
