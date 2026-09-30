"""Public HTTPS/browser checks. Changes demo order 1 through admin, then restores its original cost."""
import json
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from app.config import ROOT, Settings


def main():
    s=Settings.from_env();base=s.public_base_url;artifacts=ROOT/'artifacts';artifacts.mkdir(exist_ok=True)
    results=[]
    with httpx.Client(base_url=base,timeout=20) as client:
        before=client.get('/api/orders/1').json()
        for path,code in [('/api/health',200),('/api/dashboard',200),('/admin',401),('/.env',404),('/data/app.db',404),('/static/',404)]:
            r=client.get(path);assert r.status_code==code,(path,r.status_code)
            results.append(f'{path}: HTTP {code} verified over HTTPS')
        assert client.post('/telegram/webhook',json={'update_id':1}).status_code==403
        assert client.post('/telegram/webhook',json={'update_id':1},headers={'X-Telegram-Bot-Api-Secret-Token':'invalid'}).status_code==403
        results.append('Webhook rejects missing and wrong secret: PASS')
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
                context=browser.new_context(viewport={'width':1440,'height':1100},http_credentials={'username':s.admin_username,'password':s.admin_password})
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base);page.locator('.order-card').first.wait_for();assert page.locator('.order-card').count()==24
                page.screenshot(path=str(artifacts/'10-dashboard-public.png'),full_page=True)
                page.locator('#board').screenshot(path=str(artifacts/'11-board-public.png'))
                page.locator('.order-link[data-order="5"]').click();page.screenshot(path=str(artifacts/'12-problem-public.png'))
                page.locator('#close-details').click();page.goto(base+'/admin');page.locator('#admin-order option').first.wait_for(state='attached')
                page.fill('#rework','85000');page.locator('#save').click();page.locator('#admin-result').wait_for()
                assert 'Сохранено' in page.locator('#admin-result').inner_text()
                page.screenshot(path=str(artifacts/'13-admin-public.png'))
                after=client.get('/api/orders/1').json()
                assert after['costs']['rework_actual']==85000
                assert after['economy']['actual']['margin_income']==25000
                assert after['economy']['actual']['margin_percent']==8.33
                assert after['low_margin']
                assert after['history'][0]['source']=='admin'
                page.goto(base);page.locator('.order-link[data-order="1"]').click()
                page.screenshot(path=str(artifacts/'14-rework-detail-public.png'))
                page.locator('#economy').screenshot(path=str(artifacts/'15-rework-economy-public.png'))
                results.append('Public browser admin -> backend -> saved cost 85000 -> refreshed public dashboard: margin 25000 / 8.33%, warning and history: PASS')
                page.locator('#close-details').click();page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(artifacts/'16-mobile-public.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                assert not errors,errors
                results.append('Public desktop/mobile UI; JavaScript errors: 0')
                browser.close()
        finally:
            response=client.post('/api/admin/orders/1/rework',auth=(s.admin_username,s.admin_password),
                                 headers={'X-Requested-With':'kitchen-control'},json={'rework_actual':before['costs']['rework_actual']})
            assert response.status_code==200,response.status_code
            results.append('Original rework cost restored through authenticated API; audit history retained')
    (artifacts/'public-results.json').write_text(json.dumps({'url':base,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    for result in results:print(result)


if __name__=='__main__':main()
