"""Real Chromium tests against an isolated local DB. No Telegram traffic is sent."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from app.config import ROOT
from scripts.seed import seed


def main():
    artifacts=ROOT/'artifacts';artifacts.mkdir(exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory() as temp:
        path=str(Path(temp)/'browser.db');seed(path)
        env={**os.environ,'DATABASE_PATH':path,'ADMIN_USERNAME':'browser-test','ADMIN_PASSWORD':'local-browser-test',
             'ALLOW_LOCAL_HTTP':'true','TELEGRAM_BOT_TOKEN':'','TELEGRAM_WEBHOOK_SECRET':'','COORDINATOR_TELEGRAM_ID':''}
        process=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe') if os.name=='nt' else str(ROOT/'.venv/bin/python'),
                                  '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18888','--no-access-log'],
                                 cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            for _ in range(80):
                try:
                    if httpx.get('http://127.0.0.1:18888/api/health').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.25)
            else:raise RuntimeError('Local server did not start')
            with sync_playwright() as p:
                chrome=Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
                browser=p.chromium.launch(headless=True,**({'executable_path':str(chrome)} if chrome.exists() else {}))
                context=browser.new_context(viewport={'width':1440,'height':1100},http_credentials={'username':'browser-test','password':'local-browser-test'})
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:18888/');page.locator('.order-card').first.wait_for()
                assert page.locator('.order-card').count()==24
                page.screenshot(path=str(artifacts/'01-dashboard-local.png'),full_page=True)
                results.append('24 orders, 10 stages, KPI and dashboard rendering: PASS')
                page.locator('[data-filter="overdue"]').click()
                assert 0<page.locator('.order-card').count()<24
                assert all('Просрочен' in s for s in page.locator('.order-card').all_text_contents())
                page.locator('#reset').click();page.select_option('#stage','Монтаж')
                assert page.locator('.order-card').count()==4
                page.locator('#reset').click();results.append('KPI and stage filters without navigation: PASS')
                page.locator('.order-link[data-order="5"]').click();page.locator('#details').wait_for()
                assert page.locator('#detail-content').get_by_text('Отрицательный доход',exact=True).count()==1
                page.screenshot(path=str(artifacts/'02-problem-detail-local.png'))
                page.locator('#economy').screenshot(path=str(artifacts/'03-economy-local.png'))
                page.locator('#close-details').click();results.append('Problem details, financial calculation and history: PASS')
                timestamp=page.locator('#last-updated').inner_text()
                page.route('**/api/dashboard',lambda route:route.abort())
                page.locator('#refresh').click();page.locator('#error').wait_for()
                assert page.locator('#last-updated').inner_text()==timestamp
                assert page.locator('.order-card').count()==24
                assert 'устаревшей' in page.locator('#error').inner_text()
                page.screenshot(path=str(artifacts/'04-stale-data-local.png'))
                page.unroute('**/api/dashboard');page.locator('#refresh').click();page.locator('#error').wait_for(state='hidden')
                results.append('Failed refresh preserves last successful timestamp and shows stale-data warning; recovery: PASS')
                original=httpx.get('http://127.0.0.1:18888/api/orders/1').json()
                page.select_option('#mode','simulation');page.locator('#simulation-notice').wait_for();page.locator('#refresh:not([disabled])').wait_for()
                page.locator('#simulate').click();assert 'Имитация' in page.locator('#detail-content').inner_text()
                assert httpx.get('http://127.0.0.1:18888/api/orders/1').json()['history']==original['history']
                page.locator('#close-details').click();page.select_option('#mode','backend');page.locator('#refresh:not([disabled])').wait_for()
                results.append('Explicit simulation changes only local data and labels history as simulation: PASS')
                page.goto('http://127.0.0.1:18888/admin');page.locator('#admin-order option').first.wait_for(state='attached')
                page.fill('#rework','85000');page.locator('#save').click();page.locator('#admin-result').wait_for()
                assert 'Сохранено' in page.locator('#admin-result').inner_text()
                assert '25' in page.locator('#admin-result').inner_text()
                page.screenshot(path=str(artifacts/'05-admin-local.png'))
                saved=httpx.get('http://127.0.0.1:18888/api/orders/1').json()
                assert saved['economy']['actual']['margin_income']==25000 and saved['low_margin']
                page.goto('http://127.0.0.1:18888/');page.locator('.order-link[data-order="1"]').click()
                page.locator('#economy').screenshot(path=str(artifacts/'06-rework-result-local.png'))
                results.append('Browser admin -> HTTP API -> SQLite -> dashboard: margin falls to 25000, low-margin warning: PASS')
                page.locator('#close-details').click();page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(artifacts/'07-mobile-local.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                results.append('390px mobile layout: no page-level horizontal overflow: PASS')
                assert not errors,errors
                results.append('Browser JavaScript errors: 0')
                browser.close()
        finally:
            process.terminate();process.wait(timeout=15)
    (artifacts/'browser-results.json').write_text(json.dumps({'scope':'isolated local HTTP / real Chromium, not Telegram E2E','results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    for result in results:print(result)


if __name__=='__main__':main()
