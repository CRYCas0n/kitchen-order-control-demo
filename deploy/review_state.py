"""Run on the VPS: read-only deployment and historical Telegram verification, no secrets in output."""
import hashlib
import json
import stat
import subprocess
from pathlib import Path

import httpx

from app.config import Settings
from app.database import connect


def main():
    settings=Settings.from_env()
    report={}
    with connect(settings.database_path) as db:
        report['integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
        report['counts']={table:db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                          for table in ('orders','costs','tasks','history','telegram_users')}
        report['order_3']=dict(db.execute('SELECT stage,completed_date,problem_status FROM orders WHERE id=3').fetchone())
        report['live_problem']=dict(db.execute("SELECT id,event_type,source,telegram_update_id FROM history WHERE telegram_update_id=586212957").fetchone())
        report['live_completion']=dict(db.execute("SELECT id,event_type,source,telegram_update_id FROM history WHERE telegram_update_id=586212965").fetchone())
        report['notification']=dict(db.execute('SELECT id,status,notification FROM telegram_outbox WHERE id=24').fetchone())
        report['outbox_counts']={r[0]:r[1] for r in db.execute('SELECT status,COUNT(*) FROM telegram_outbox GROUP BY status')}
        report['future_completions']=db.execute("SELECT COUNT(*) FROM orders WHERE completed_date>'2026-09-30'").fetchone()[0]
    env=Path('.env').stat()
    report['env_permissions']=oct(stat.S_IMODE(env.st_mode))
    report['env_owned_by_root']=env.st_uid==0
    report['local_http_disabled']=not settings.allow_local_http
    report['service']=subprocess.check_output(['systemctl','is-active','kitchen-control'],text=True).strip()
    report['enabled']=subprocess.check_output(['systemctl','is-enabled','kitchen-control'],text=True).strip()
    report['service_user']=subprocess.check_output(['systemctl','show','-p','User','--value','kitchen-control'],text=True).strip()
    report['caddy_sha256']=hashlib.sha256(Path('/opt/caddy/Caddyfile').read_bytes()).hexdigest()
    listeners=subprocess.check_output(['ss','-ltn'],text=True).splitlines()
    bound=[line.split()[3] for line in listeners if ':18080 ' in line]
    report['backend_listeners']=bound
    with httpx.Client(timeout=20) as client:
        try:
            response=client.post(f'https://api.telegram.org/bot{settings.telegram_bot_token}/getWebhookInfo')
            data=response.json()
            assert response.is_success and data.get('ok')
            info=data['result']
            report['webhook']={k:info.get(k) for k in ['url','pending_update_count','last_error_date']}
            report['webhook_matches']=info['url']==settings.public_base_url+'/telegram/webhook'
        except Exception:
            report['webhook_check']='FAIL (details suppressed to protect token)'
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
