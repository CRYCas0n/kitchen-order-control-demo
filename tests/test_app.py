import asyncio
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.calculations import deadlines, economics
from app.config import COST_FIELDS, Settings
from app.database import connect, dashboard, get_order
from app.main import create_app
from app.telegram import drain_outbox, process_update
from scripts.seed import seed


class FinancialTests(unittest.TestCase):
    def setUp(self):
        self.costs = dict(zip((f"{f}_actual" for f in COST_FIELDS), [300000,120000,30000,10000,15000,15000,10000]))

    def test_control_example(self):
        result = economics(self.costs)
        self.assertEqual((result['variable_costs'], result['margin_income'], result['margin_percent']), (200000,100000,33.33))

    def test_rework_delta(self):
        before = economics(self.costs)['margin_income']
        self.costs['rework_actual'] += 35000
        self.assertEqual(economics(self.costs)['margin_income'], before-35000)

    def test_null_is_incomplete(self):
        self.costs['materials_actual'] = None
        self.assertFalse(economics(self.costs)['complete'])
        self.assertIsNone(economics(self.costs)['margin_income'])

    def test_zero_is_known(self):
        self.costs['rework_actual'] = 0
        self.assertTrue(economics(self.costs)['complete'])
        self.assertEqual(economics(self.costs)['margin_income'], 110000)

    def test_zero_revenue(self):
        self.costs['revenue_actual'] = 0
        result = economics(self.costs)
        self.assertIsNone(result['margin_percent'])
        self.assertTrue(result['negative_margin'])

    def test_dates_and_completed_orders(self):
        order = dict(stage='Монтаж', promised_date_initial='2026-09-29', forecast_date='2026-10-01', completed_date=None)
        self.assertTrue(deadlines(order)['overdue'])
        order['promised_date_initial'] = '2026-09-30'
        self.assertFalse(deadlines(order)['overdue'])
        self.assertTrue(deadlines(order)['delay_risk'])
        order.update(stage='Завершён',completed_date='2026-09-29')
        self.assertEqual(deadlines(order)['deadline_label'], 'Завершён вовремя')
        order['completed_date'] = '2026-10-01'
        self.assertEqual(deadlines(order)['deadline_label'], 'Завершён с опозданием')
        self.assertFalse(deadlines(order)['overdue'])


class FakeTelegram:
    def __init__(self, status='sent'):
        self.calls = []
        self.status = status

    async def call(self, method, body):
        self.calls.append((method,body))
        return self.status, None if self.status=='sent' else 'test transport failure'


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name)/'app.db')
        seed(self.path)
        self.settings = Settings(database_path=self.path, admin_password='test-only-password',
                                 telegram_webhook_secret='test-secret', coordinator_telegram_id=303)
        self.fake = FakeTelegram()
        self.app = create_app(self.settings, self.fake, worker=False)
        self.client = TestClient(self.app, base_url='https://testserver')
        self.client.__enter__()
        with connect(self.path) as db:
            db.executemany('INSERT INTO telegram_users VALUES (?,?,?,?,1)', [
                (101,'Тестовый монтажник','installer','INSTALL-01'),
                (202,'Тестовый замерщик','measurer','MEASURE-01'),
                (303,'Тестовый координатор','coordinator','COORD-01'),
                (404,'Другой монтажник','installer','INSTALL-02')])
        self.uid = 1000

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def send(self, text=None, callback=None, user=101, update_id=None, photo=None):
        self.uid += 1
        msg = {'from':{'id':user},'chat':{'id':user,'type':'private'}}
        if text is not None:msg['text']=text
        if photo:msg['photo']=[{'file_id':photo}]
        update = {'update_id':update_id or self.uid}
        if callback:
            update['callback_query']={'id':str(self.uid),'from':{'id':user},'message':msg,'data':callback}
        else:update['message']=msg
        response=self.client.post('/telegram/webhook',json=update,headers={'X-Telegram-Bot-Api-Secret-Token':'test-secret'})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def nonce(self, user=101):
        with connect(self.path) as db:
            return db.execute('SELECT nonce FROM telegram_sessions WHERE telegram_id=?',(user,)).fetchone()[0]

    def problem(self):
        self.send(callback='problem:1')
        self.send('Комплектация')
        self.send('Нет фасада')
        self.send('Привезти фасад')
        return self.nonce()

    def test_seed_repeated_and_dataset(self):
        self.assertFalse(seed(self.path))
        data=self.client.get('/api/dashboard').json()
        self.assertEqual(len(data['orders']),24)
        self.assertFalse(any(o['data_error'] for o in data['orders']))
        self.assertEqual(len(set(o['city'] for o in data['orders'] if o['sales_point_type']=='Дилер')),5)
        self.assertTrue(all(data['kpis'].values()))

    def test_dashboard_recalculates_after_admin_update(self):
        before = self.client.get('/api/dashboard').json()
        self.assertEqual(before['kpis'], before['summary']['kpis'])
        response = self.client.post('/api/admin/orders/1/rework', json={'rework_actual':85000},
                                    auth=('coordinator','test-only-password'), headers={'X-Requested-With':'kitchen-control'})
        self.assertEqual(response.status_code, 200)
        after = self.client.get('/api/dashboard').json()
        self.assertEqual(after['summary']['finance']['margin_income'], before['summary']['finance']['margin_income'] - 75000)
        self.assertEqual(after['summary']['margins']['low'], before['summary']['margins']['low'] + 1)
        self.assertEqual(after['summary']['margins']['normal'], before['summary']['margins']['normal'] - 1)
        self.assertEqual(after['kpis']['low_margin'], before['kpis']['low_margin'] + 1)
        self.assertEqual(after['summary']['finance']['complete_count'], 23)

    def test_problem_transaction_duplicate_and_notification(self):
        nonce=self.problem()
        self.send(callback='confirm:'+nonce,update_id=9000)
        duplicate=self.send(callback='confirm:'+nonce,update_id=9000)
        self.assertTrue(duplicate['duplicate'])
        asyncio.run(drain_outbox(self.path,self.fake))
        asyncio.run(drain_outbox(self.path,self.fake))
        notifications=[b for m,b in self.fake.calls if b.get('chat_id')==303]
        self.assertEqual(len(notifications),1)
        self.assertIn('Привезти фасад',notifications[0]['text'])
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM history WHERE telegram_update_id=9000').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE notification=1").fetchone()[0],1)
            o=get_order(db,1)
        self.assertEqual(o['problem_status'],'open')
        self.assertEqual(o['next_action'],'Привезти фасад')
        self.assertTrue(any(h['event_type']=='notification_sent' for h in o['history']))

    def test_permission_checked_on_list_and_mutation(self):
        self.send('/tasks',user=404)
        with connect(self.path) as db:
            reply=json.loads(db.execute("SELECT body FROM telegram_outbox WHERE method='sendMessage' ORDER BY id DESC").fetchone()[0])
        self.assertNotIn('task:1"',json.dumps(reply))
        self.send(callback='accept:1',user=404)
        self.send(callback='problem:1',user=404)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT status FROM tasks WHERE id=1').fetchone()[0],'new')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM telegram_sessions').fetchone()[0],0)

    def test_permission_rechecked_mid_dialog(self):
        nonce=self.problem()
        with connect(self.path) as db:db.execute("UPDATE tasks SET assignee_code='INSTALL-02' WHERE id=1")
        self.send(callback='confirm:'+nonce)
        self.assertFalse(self.client.get('/api/orders/1').json()['open_problem'])

    def test_installer_completion_goes_to_acceptance_with_photo(self):
        self.send(callback='done:1');n=self.nonce()
        self.send(callback='check:'+n);self.send('Проверено, замечаний нет');self.send(photo='test-file-id')
        self.send(callback='confirm:'+n)
        order=self.client.get('/api/orders/1').json()
        self.assertEqual(order['stage'],'Приёмка')
        self.assertIsNone(order['completed_date'])
        self.assertNotIn('test-file-id',json.dumps(order))
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT status FROM tasks WHERE id=1').fetchone()[0],'completed')
            self.assertEqual(db.execute('SELECT photo_file_id FROM tasks WHERE id=1').fetchone()[0],'test-file-id')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM telegram_sessions').fetchone()[0],0)
        self.send(callback='done:1')
        self.assertEqual(self.client.get('/api/orders/1').json()['stage'],'Приёмка')

    def test_measurer_completion(self):
        self.send(callback='done:2',user=202);n=self.nonce(202)
        self.send(callback='check:'+n,user=202);self.send('Размеры проверены',user=202)
        self.send(callback='skip:'+n,user=202);self.send(callback='confirm:'+n,user=202)
        self.assertEqual(self.client.get('/api/orders/2').json()['stage'],'Проектирование')

    def test_transfer_preserves_original_and_forecast(self):
        before=self.client.get('/api/orders/1').json()
        self.send(callback='transfer:1');self.send('2026-02-30')
        with connect(self.path) as db:self.assertEqual(db.execute('SELECT step FROM telegram_sessions').fetchone()[0],'date')
        self.send('2026-10-06');self.send('Ждём фасад');self.send(callback='confirm:'+self.nonce())
        after=self.client.get('/api/orders/1').json()
        for key in ('promised_date_initial','forecast_date'):self.assertEqual(before[key],after[key])
        self.assertEqual(after['tasks'][0]['proposed_date'],'2026-10-06')

    def test_stale_button_and_cancel(self):
        self.send(callback='done:1');old=self.nonce();self.send('/cancel');self.send(callback='done:1')
        self.send(callback='check:'+old)
        with connect(self.path) as db:self.assertEqual(db.execute('SELECT step FROM telegram_sessions').fetchone()[0],'checklist')
        self.send('/cancel')
        with connect(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM telegram_sessions').fetchone()[0],0)

    def test_restart_preserves_dialog(self):
        self.send(callback='problem:1');self.send('Комплектация')
        app2=create_app(self.settings,self.fake,worker=False)
        with TestClient(app2,base_url='https://testserver') as client:
            r=client.post('/telegram/webhook',headers={'X-Telegram-Bot-Api-Secret-Token':'test-secret'},json={
                'update_id':99999,'message':{'from':{'id':101},'chat':{'id':101,'type':'private'},'text':'Нет фасада'}})
            self.assertEqual(r.status_code,200)
        with connect(self.path) as db:self.assertEqual(db.execute('SELECT step FROM telegram_sessions').fetchone()[0],'help')

    def test_unknown_and_inactive_users(self):
        self.send('/start',user=909)
        with connect(self.path) as db:
            reply=json.loads(db.execute('SELECT body FROM telegram_outbox ORDER BY id DESC').fetchone()[0])
            self.assertNotIn('reply_markup',reply)
            self.assertIn('909',reply['text'])
            db.execute('UPDATE telegram_users SET active=0 WHERE telegram_id=101')
        self.send(callback='accept:1')
        self.assertEqual(self.client.get('/api/orders/1').json()['tasks'][0]['status'],'new')

    def test_secret_and_invalid_updates(self):
        self.assertEqual(self.client.post('/telegram/webhook',json={'update_id':1}).status_code,403)
        self.assertEqual(self.client.post('/telegram/webhook',json={'update_id':1},headers={'X-Telegram-Bot-Api-Secret-Token':'wrong'}).status_code,403)
        for payload in ([],{'update_id':'x'},{'update_id':True}):
            self.assertEqual(self.client.post('/telegram/webhook',json=payload,headers={'X-Telegram-Bot-Api-Secret-Token':'test-secret'}).status_code,422)

    def test_admin_auth_input_csrf_and_finance(self):
        url='/api/admin/orders/1/rework'
        auth=('coordinator','test-only-password');headers={'X-Requested-With':'kitchen-control'}
        self.assertEqual(self.client.post(url,json={'rework_actual':45000}).status_code,401)
        self.assertEqual(self.client.get('/admin').status_code,401)
        self.assertEqual(self.client.post(url,json={'rework_actual':45000},auth=auth).status_code,403)
        self.assertEqual(self.client.post(url,json={'rework_actual':45000},auth=auth,headers={**headers,'Origin':'https://evil.example'}).status_code,403)
        for value in (-1,None,True,'abc','NaN','Infinity','1.001',1000000001):
            self.assertEqual(self.client.post(url,json={'rework_actual':value},auth=auth,headers=headers).status_code,422,str(value))
        response=self.client.post(url,json={'rework_actual':'45000.00'},auth=auth,headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['economy']['actual']['margin_income'],65000)
        with connect(self.path) as db:self.assertEqual(db.execute('SELECT rework_actual FROM costs WHERE order_id=1').fetchone()[0],45000)
        self.assertEqual(self.client.get('/api/orders/1/history').json()[0]['source'],'admin')

    def test_admin_http_rejected(self):
        with TestClient(self.app,base_url='http://testserver') as client:
            self.assertEqual(client.get('/admin',auth=('coordinator','test-only-password')).status_code,403)

    def test_bad_row_does_not_break_dashboard(self):
        with connect(self.path) as db:db.execute("UPDATE orders SET forecast_date='2026-02-30' WHERE id=5")
        response=self.client.get('/api/dashboard')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['orders'][4]['data_error'])
        self.assertFalse(response.json()['orders'][0]['data_error'])

    def test_database_constraints(self):
        with connect(self.path) as db:
            for query in ("UPDATE orders SET order_number='КФ-2602' WHERE id=1", "UPDATE orders SET stage='Wrong' WHERE id=1", "UPDATE tasks SET order_id=999 WHERE id=1", "UPDATE costs SET rework_actual=-1 WHERE order_id=1"):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(query)

    def test_private_files_and_cache_headers(self):
        for path in ('/.env','/data/app.db','/static/app.db','/static/../.env','/static/','/docs','/static/admin.html'):
            self.assertNotEqual(self.client.get(path).status_code,200,path)
        response=self.client.get('/api/health')
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertNotIn(self.path,response.text)
        self.assertEqual(response.json()['database'],'ok')
        self.assertEqual(self.client.get('/api/orders/99999').status_code,404)

    def test_uncertain_delivery_is_not_retried(self):
        self.send('/start');api=FakeTelegram('uncertain')
        asyncio.run(drain_outbox(self.path,api));asyncio.run(drain_outbox(self.path,api))
        self.assertEqual(len(api.calls),1)
        with connect(self.path) as db:self.assertEqual(db.execute('SELECT status FROM telegram_outbox').fetchone()[0],'uncertain')

    def test_rollback_does_not_claim_update(self):
        with self.assertRaises(RuntimeError):
            with connect(self.path) as db:
                db.execute('BEGIN IMMEDIATE')
                process_update(db,{'update_id':123456},self.settings)
                raise RuntimeError('simulated crash before commit')
        with connect(self.path) as db:self.assertIsNone(db.execute('SELECT * FROM telegram_updates WHERE update_id=123456').fetchone())

    def test_concurrent_duplicate_is_one_operation(self):
        update={'update_id':777777,'callback_query':{'id':'concurrent','from':{'id':101},
                'message':{'chat':{'id':101,'type':'private'}},'data':'accept:1'}}
        def operation():
            with connect(self.path) as db:
                db.execute('BEGIN IMMEDIATE')
                return process_update(db,update,self.settings)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:operation(),range(4)))
        self.assertEqual(sum(r.get('duplicate',False) for r in results),3)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM history WHERE telegram_update_id=777777').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE dedupe_key='777777:reply'").fetchone()[0],1)


if __name__=='__main__':unittest.main()
