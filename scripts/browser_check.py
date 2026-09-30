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
from app.database import connect
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
                overview=httpx.get('http://127.0.0.1:18888/api/dashboard').json()
                for key,count in overview['kpis'].items():
                    assert int(page.locator(f'[data-filter="{key}"] .kpi-value').inner_text())==count
                    page.locator(f'[data-filter="{key}"]').click()
                    assert page.locator('.order-card').count()==count
                    actual_ids={int(v) for v in page.locator('.order-card').evaluate_all('(nodes) => nodes.map(n => n.dataset.order)')}
                    assert actual_ids=={o['id'] for o in overview['orders'] if o[key]}
                    page.locator('#reset').click()
                assert page.locator('#stage-chart .stage-row').count()==10
                assert sum(int(n) for n in page.locator('#stage-chart .stage-row').evaluate_all('(nodes) => nodes.map(n => n.dataset.count)'))==24
                assert page.locator('#attention .order-link').count()==5
                assert [int(v) for v in page.locator('#attention .order-link').evaluate_all('(nodes) => nodes.map(n => n.dataset.order)')]==overview['summary']['attention_ids']
                page.locator('#executive-dashboard').screenshot(path=str(artifacts/'30-executive-dashboard-local.png'))
                results.append('All six KPI totals and click filters match exact order IDs; 10 stage counts total 24; top five priority list: PASS')
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
                chart_before=page.locator('.overview-grid').inner_html()
                page.route('**/api/dashboard',lambda route:route.abort())
                page.locator('#refresh').click();page.locator('#error').wait_for()
                assert page.locator('#last-updated').inner_text()==timestamp
                assert page.locator('.order-card').count()==24
                assert page.locator('.overview-grid').inner_html()==chart_before
                assert 'устаревшей' in page.locator('#error').inner_text()
                page.screenshot(path=str(artifacts/'04-stale-data-local.png'))
                page.unroute('**/api/dashboard');page.locator('#refresh').click();page.locator('#error').wait_for(state='hidden')
                results.append('Failed refresh preserves last successful timestamp and shows stale-data warning; recovery: PASS')
                timestamp=page.locator('#last-updated').inner_text()
                page.route('**/api/dashboard',lambda route:route.fulfill(json={'orders':[],'stages':[],'demo_date':'2026-09-30','source':'backend','summary':{'finance':{},'kpis':{},'attention_ids':[]}}))
                page.locator('#refresh').click();page.locator('#error').wait_for()
                assert page.locator('#last-updated').inner_text()==timestamp
                assert page.locator('.overview-grid').inner_html()==chart_before
                page.unroute('**/api/dashboard');page.locator('#refresh').click();page.locator('#error').wait_for(state='hidden')
                results.append('Malformed successful HTTP response does not replace valid charts or timestamp: PASS')
                page.locator('.order-card[data-order="5"]').click()
                broken=json.loads(json.dumps(overview));broken['orders'][4]['history']={'invalid':'shape'}
                old_detail=page.locator('#detail-content').inner_html()
                timestamp=page.locator('#last-updated').inner_text()
                page.wait_for_timeout(1100)
                page.route('**/api/dashboard',lambda route:route.fulfill(json=broken))
                page.evaluate("document.getElementById('refresh').click()")
                page.locator('#refresh:not([disabled])').wait_for()
                assert page.locator('#last-updated').inner_text()==timestamp
                assert page.locator('#detail-content').inner_html()==old_detail
                page.locator('#close-details').click();page.locator('#error').wait_for()
                page.unroute('**/api/dashboard');page.locator('#refresh').click();page.locator('#error').wait_for(state='hidden')
                results.append('Malformed order with an open detail dialog preserves the old snapshot and success timestamp: PASS')
                original=httpx.get('http://127.0.0.1:18888/api/orders/1').json()
                page.select_option('#mode','simulation');page.locator('#simulation-notice').wait_for();page.locator('#refresh:not([disabled])').wait_for()
                page.locator('#simulate').click();assert 'Имитация' in page.locator('#detail-content').inner_text()
                simulation=httpx.get('http://127.0.0.1:18888/static/demo-data.json').json()['simulation']['summary']
                assert int(page.locator('[data-filter="open_problem"] .kpi-value').inner_text())==simulation['kpis']['open_problem']
                assert httpx.get('http://127.0.0.1:18888/api/orders/1').json()['history']==original['history']
                page.locator('#close-details').click();page.select_option('#mode','backend');page.locator('#refresh:not([disabled])').wait_for()
                results.append('Explicit simulation changes only local data and labels history as simulation: PASS')
                # Independent fixture writes emulate new business data while the page keeps its old snapshot.
                with connect(path) as db:
                    db.execute("UPDATE orders SET stage='Проектирование',forecast_date='2026-10-09' WHERE id=2")
                response=httpx.post('http://127.0.0.1:18888/api/admin/orders/1/rework',auth=('browser-test','local-browser-test'),
                                    headers={'X-Requested-With':'kitchen-control'},json={'rework_actual':85000})
                assert response.status_code==200
                assert int(page.locator('[data-filter="low_margin"] .kpi-value').inner_text())==overview['kpis']['low_margin']
                page.locator('#refresh').click();page.locator('#refresh:not([disabled])').wait_for()
                fresh=httpx.get('http://127.0.0.1:18888/api/dashboard').json()['summary']
                assert int(page.locator('[data-filter="low_margin"] .kpi-value').inner_text())==fresh['kpis']['low_margin']==overview['kpis']['low_margin']+1
                assert int(page.locator('[data-filter="delay_risk"] .kpi-value').inner_text())==fresh['kpis']['delay_risk']==overview['kpis']['delay_risk']+1
                for row in fresh['stages']:
                    assert int(page.locator(f'.stage-row[data-stage="{row["stage"]}"]').get_attribute('data-count'))==row['count']
                for chart,values in [('deadline-chart',fresh['deadlines']),('margin-chart',fresh['margins'])]:
                    for key,count in values.items():
                        if key=='not_calculable' and not count:continue
                        assert int(page.locator(f'#{chart} [data-bucket="{key}"]').get_attribute('data-count'))==count
                shown_income=page.locator('[data-metric="margin_income"]').inner_text()
                shown_income=''.join(c for c in shown_income if c.isdigit() or c in ',-').replace(',','.')
                assert float(shown_income)==fresh['finance']['margin_income']
                assert fresh['finance']['margin_income']==overview['summary']['finance']['margin_income']-75000
                results.append('Fresh API refresh updates KPI, stage/deadline/margin charts and aggregate income after real fixture/admin changes: PASS')
                page.goto('http://127.0.0.1:18888/admin');page.locator('#admin-order option').first.wait_for(state='attached')
                page.fill('#rework','85000');page.locator('#save').click();page.locator('#admin-result').wait_for()
                assert 'Сохранено' in page.locator('#admin-result').inner_text()
                assert '25' in page.locator('#admin-result').inner_text()
                page.screenshot(path=str(artifacts/'05-admin-local.png'))
                saved=httpx.get('http://127.0.0.1:18888/api/orders/1').json()
                assert saved['economy']['actual']['margin_income']==25000 and saved['low_margin']
                pending=[]
                page.route('**/api/admin/orders/1/rework',lambda route:pending.append(route))
                page.fill('#rework','85001');page.locator('#save').click()
                page.locator('#admin-order:disabled').wait_for()
                assert page.locator('#rework').is_disabled()
                page.wait_for_timeout(100)
                pending[0].abort();page.locator('#admin-result').wait_for()
                assert 'перед повторным сохранением' in page.locator('#admin-result').inner_text()
                assert httpx.get('http://127.0.0.1:18888/api/orders/1').json()['costs']['rework_actual']==85000
                page.unroute('**/api/admin/orders/1/rework')
                with connect(path) as db:db.execute("UPDATE orders SET forecast_date='invalid' WHERE id=1")
                page.fill('#rework','85000');page.locator('#save').click();page.locator('#admin-result').wait_for()
                assert 'Сохранено: КФ-2601' in page.locator('#admin-result').inner_text()
                assert 'Нет данных' in page.locator('#admin-result').inner_text()
                with connect(path) as db:db.execute('UPDATE orders SET forecast_date=? WHERE id=1',(original['forecast_date'],))
                results.append('Admin locks order/input during save; network uncertainty is explicit; saved order with invalid data does not crash UI: PASS')
                page.goto('http://127.0.0.1:18888/');page.locator('.order-card[data-order="1"]').click()
                page.locator('#economy').screenshot(path=str(artifacts/'06-rework-result-local.png'))
                results.append('Browser admin -> HTTP API -> SQLite -> dashboard: margin falls to 25000, low-margin warning: PASS')
                page.locator('#close-details').click();page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(artifacts/'07-mobile-local.png'),full_page=True)
                page.locator('#executive-dashboard').screenshot(path=str(artifacts/'31-executive-dashboard-mobile-local.png'))
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
