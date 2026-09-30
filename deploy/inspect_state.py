import json
import sqlite3
import subprocess

c=sqlite3.connect('data/app.db');c.row_factory=sqlite3.Row
print('Users:',json.dumps([dict(r) for r in c.execute('SELECT telegram_id,display_name,role,assignee_code,active FROM telegram_users')],ensure_ascii=False))
print('Outbox:',json.dumps([dict(r) for r in c.execute('SELECT id,update_id,status,method,notification,error FROM telegram_outbox ORDER BY id DESC LIMIT 12')],ensure_ascii=False))
print('Recent new user IDs:',[json.loads(r[0]).get('chat_id') for r in c.execute("SELECT body FROM telegram_outbox WHERE body LIKE '%Telegram ID%' ORDER BY id DESC LIMIT 5")])
print('History:',json.dumps([dict(r) for r in c.execute("SELECT id,order_id,event_type,source,comment FROM history WHERE source!='system' ORDER BY id DESC LIMIT 6")],ensure_ascii=False))
print('Service:',subprocess.check_output(['systemctl','show','kitchen-control','-p','ActiveState','-p','UnitFileState','-p','MemoryCurrent','-p','NRestarts'],text=True))
