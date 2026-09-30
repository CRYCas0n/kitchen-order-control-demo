import hashlib
import json
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

def signature():
    with sqlite3.connect('data/app.db') as c:
        rows=c.execute('SELECT id,stage,promised_date_initial,forecast_date FROM orders ORDER BY id').fetchall()
        return hashlib.sha256(json.dumps(rows).encode()).hexdigest()

before=signature()
subprocess.run(['systemctl','stop','kitchen-control'],check=True)
assert subprocess.run(['systemctl','is-active','--quiet','kitchen-control']).returncode!=0
subprocess.run(['systemctl','start','kitchen-control'],check=True)
for _ in range(30):
    try:
        with urlopen('http://172.18.0.1:18080/api/health',timeout=2) as r:
            if r.status==200:break
    except Exception:time.sleep(.5)
else:raise RuntimeError('Health unavailable after start')
subprocess.run(['systemctl','restart','kitchen-control'],check=True)
for _ in range(30):
    try:
        with urlopen('http://172.18.0.1:18080/api/health',timeout=2) as r:
            if r.status==200:break
    except Exception:time.sleep(.5)
else:raise RuntimeError('Health unavailable after restart')
assert signature()==before
assert subprocess.check_output(['systemctl','is-enabled','kitchen-control'],text=True).strip()=='enabled'
backup=Path('data/verified-backup.db')
if not backup.exists():
    with sqlite3.connect('data/app.db') as source, sqlite3.connect(backup) as target:source.backup(target)
with sqlite3.connect(backup) as target:
    assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert target.execute('SELECT count(*) FROM orders').fetchone()[0]==24
with sqlite3.connect('data/app.db') as c:
    print('Admin writes persisted in SQLite:', c.execute("SELECT COUNT(*) FROM history WHERE source='admin'").fetchone()[0])
print('PASS: stop/start/restart, DB persistence, enabled at boot, SQLite backup integrity. Actual host reboot: NOT TESTED.')
