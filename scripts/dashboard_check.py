"""Read-only HTTPS/browser verification of the executive dashboard."""
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from app.config import ROOT, Settings


def main():
    base = Settings.from_env().public_base_url
    artifacts = ROOT / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    with httpx.Client(base_url=base, timeout=20) as client:
        response = client.get('/api/dashboard')
        response.raise_for_status()
        data = response.json()
    orders, summary = data['orders'], data['summary']
    results = []
    assert sum(row['count'] for row in summary['stages']) == len(orders)
    assert sum(summary['deadlines'].values()) + summary['invalid_count'] == len(orders)
    assert sum(summary['margins'].values()) == len(orders)
    assert not any(o['overdue'] for o in orders if o['stage'] == 'Завершён')
    complete = [o for o in orders if not o['data_error'] and o['economy']['actual']['complete']]
    revenue = sum((Decimal(str(o['costs']['revenue_actual'])) for o in complete), Decimal(0))
    income = sum((Decimal(str(o['economy']['actual']['margin_income'])) for o in complete), Decimal(0))
    percents = [Decimal(str(o['economy']['actual']['margin_percent'])) for o in complete if o['economy']['actual']['margin_percent'] is not None]
    average = float((sum(percents) / len(percents)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if percents else None
    finance = summary['finance']
    assert finance['revenue_actual'] == (float(revenue) if complete else None)
    assert finance['margin_income'] == (float(income) if complete else None)
    assert finance['average_margin_percent'] == average
    assert finance['loss_count'] == sum(o['economy']['actual']['margin_income'] < 0 for o in complete)
    results.append('Public API partitions, complete-data finance totals, arithmetic mean and completed-order exclusion: PASS')
    with sync_playwright() as p:
        chrome = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
        browser = p.chromium.launch(headless=True, **({'executable_path':str(chrome)} if chrome.exists() else {}))
        page = browser.new_page(viewport={'width':1440, 'height':1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base)
        page.locator('#stage-chart .stage-row').first.wait_for()
        for key, count in summary['kpis'].items():
            expected = {o['id'] for o in orders if o[key]}
            assert count == len(expected)
            assert int(page.locator(f'[data-filter="{key}"] .kpi-value').inner_text()) == count
            page.locator(f'[data-filter="{key}"]').click()
            actual = {int(v) for v in page.locator('.order-card').evaluate_all('(nodes) => nodes.map(n => n.dataset.order)')}
            assert actual == expected
            page.locator('#reset').click()
        for row in summary['stages']:
            assert int(page.locator(f'.stage-row[data-stage="{row["stage"]}"]').get_attribute('data-count')) == row['count']
        for chart, values in [('deadline-chart', summary['deadlines']), ('margin-chart', summary['margins'])]:
            for key, count in values.items():
                if key == 'not_calculable' and not count:
                    continue
                assert int(page.locator(f'#{chart} [data-bucket="{key}"]').get_attribute('data-count')) == count
        ids = [int(v) for v in page.locator('#attention .order-link').evaluate_all('(nodes) => nodes.map(n => n.dataset.order)')]
        assert ids == summary['attention_ids'] and len(ids) <= 5
        results.append('All six public KPI click filters, chart counts and attention list agree with API: PASS')
        page.screenshot(path=str(artifacts / '32-executive-dashboard-public.png'), full_page=True)
        timestamp = page.locator('#last-updated').inner_text()
        chart_before = page.locator('.overview-grid').inner_html()
        page.route('**/api/dashboard', lambda route: route.abort())
        page.locator('#refresh').click()
        page.locator('#error').wait_for()
        assert page.locator('#last-updated').inner_text() == timestamp
        assert page.locator('.overview-grid').inner_html() == chart_before
        page.unroute('**/api/dashboard')
        page.locator('#refresh').click()
        page.locator('#error').wait_for(state='hidden')
        results.append('Public UI failed refresh preserves previous charts/timestamp and visibly warns, then recovers: PASS')
        for width in [1100, 768, 390]:
            page.set_viewport_size({'width':width, 'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), width
        page.screenshot(path=str(artifacts / '33-executive-dashboard-mobile-public.png'), full_page=True)
        assert not errors, errors
        results.append('Responsive 1100/768/390px layout without page overflow; JavaScript errors: 0')
        browser.close()
    (artifacts / 'dashboard-public-results.json').write_text(json.dumps({
        'url':base, 'generated_at':data['generated_at'], 'scope':'read-only public API and real Chrome',
        'kpis':summary['kpis'], 'finance':finance, 'results':results,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    for result in results:
        print(result)


if __name__ == '__main__':
    main()
