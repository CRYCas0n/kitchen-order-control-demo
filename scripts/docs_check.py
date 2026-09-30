"""Check documentation links/contracts/examples against local code and an isolated SQLite."""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.config import ROOT


def main():
    names=('PROJECT_OVERVIEW USER_GUIDE TELEGRAM_GUIDE BUSINESS_RULES TECHNICAL_GUIDE API DATABASE SETUP '
           'DEPLOYMENT OPERATIONS TROUBLESHOOTING SECURITY TESTING DEMO_SCRIPT LIMITATIONS GLOSSARY '
           'TEST_RESULTS ISSUE_LOG DOCUMENTATION_REVIEW').split()
    files=[ROOT/'README.md', ROOT/'artifacts/README.md', *sorted((ROOT/'docs').glob('*.md'))]
    issues=[]
    for name in names:
        if not (ROOT/'docs'/f'{name}.md').is_file():issues.append('Missing document: '+name)
    links=0
    for file in files:
        content=file.read_text(encoding='utf-8')
        without_code=re.sub(r'```.*?```','',content,flags=re.S)
        for raw in re.findall(r'\[[^\]\n]*\]\(([^)]+)\)',without_code):
            target=raw.strip('<>')
            if urlsplit(target).scheme or target.startswith('#'):continue
            links+=1
            target=unquote(target.split('#',1)[0])
            if not (file.parent/target).exists():issues.append(f'{file.relative_to(ROOT)}: broken link {target}')
        for code in re.findall(r"<<'PY'\n(.*?)\nPY",content,re.S):
            try:compile(code,str(file),'exec')
            except SyntaxError as exc:issues.append(f'{file.name}: invalid Python example at line {exc.lineno}')
        for code in re.findall(r'```json\n(.*?)\n```',content,re.S):
            try:json.loads(code)
            except ValueError:issues.append(file.name+': invalid JSON example')
    api=(ROOT/'docs/API.md').read_text(encoding='utf-8')
    module=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
    routes=[]
    for node in ast.walk(module):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute) and dec.func.attr in ('get','post'):
                    method,path=dec.func.attr.upper(),dec.args[0].value
                    routes.append((method,path))
                    if f'{method} {path}' not in api and f'{method} `{path}`' not in api:
                        issues.append(f'Undocumented route: {method} {path}')
    config=ast.parse((ROOT/'app/config.py').read_text(encoding='utf-8'))
    env={n.args[0].value for n in ast.walk(config) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
         and n.func.attr=='getenv' and n.args and isinstance(n.args[0],ast.Constant)}
    example={line.split('=',1)[0] for line in (ROOT/'.env.example').read_text().splitlines() if '=' in line and not line.startswith('#')}
    if env!=example:issues.append('Environment names differ between code and .env.example')
    setup=(ROOT/'docs/SETUP.md').read_text(encoding='utf-8')
    for key in env:
        if key not in setup:issues.append('Undocumented environment variable: '+key)
    unit=(ROOT/'deploy/kitchen-control.service').read_text()
    deployment=(ROOT/'docs/DEPLOYMENT.md').read_text(encoding='utf-8')
    for value in re.findall(r'--(?:host|port|forwarded-allow-ips) ([\d.]+)',unit):
        if value not in deployment:issues.append('Undocumented service network setting: '+value)
    test_count=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for path in (ROOT/'tests').glob('test_*.py')
                   for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))))
    if f'{test_count}' not in (ROOT/'docs/TESTING.md').read_text(encoding='utf-8'):issues.append('Test count missing in TESTING')
    for command in (['-m','scripts.seed','--help'],['-m','scripts.manage','--help'],['-m','scripts.offline','--help'],
                    ['deploy/push.py','--help'],['deploy/remote.py','--help']):
        result=subprocess.run([sys.executable,*command],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if result.returncode:issues.append('CLI help failed: '+' '.join(command))
    with tempfile.TemporaryDirectory(prefix='kitchen-docs-') as directory:
        path=str(Path(directory)/'docs.db')
        # Also isolate the default app created on app.main import; no production token or worker traffic.
        os.environ.update(DATABASE_PATH=path,TELEGRAM_BOT_TOKEN='',TELEGRAM_WEBHOOK_SECRET='',
                          COORDINATOR_TELEGRAM_ID='',ADMIN_PASSWORD='',ALLOW_LOCAL_HTTP='true')
        from app.config import Settings
        from app.database import connect
        from scripts.seed import seed
        from app.main import create_app
        from fastapi.testclient import TestClient
        seed(path)
        with connect(path) as db:
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        database=(ROOT/'docs/DATABASE.md').read_text(encoding='utf-8')
        for table in tables:
            if f'### {table}\n' not in database:issues.append('Undocumented table: '+table)
        settings=Settings(database_path=path,admin_password='docs-only-password',telegram_webhook_secret='docs-only-secret')
        with TestClient(create_app(settings,worker=False),base_url='https://testserver') as client:
            fresh=client.get('/api/dashboard').json()
            summaries=[json.loads(block) for block in re.findall(r'```json\n(.*?)\n```',api,re.S)]
            documented=next((obj for obj in summaries if isinstance(obj,dict) and 'kpis' in obj),None)
            if documented!=fresh['summary']:issues.append('API summary example differs from fresh seed')
            history=next((obj for obj in summaries if isinstance(obj,list) and obj and 'event_type' in obj[0]),None)
            if history!=client.get('/api/orders/1/history').json():issues.append('API history example differs from fresh seed')
            if client.get('/api/health').json()['status']!='ok':issues.append('Health example failed')
            if client.get('/api/orders/999999').status_code!=404:issues.append('Missing order contract failed')
            if client.get('/api/orders/0').status_code!=422:issues.append('Invalid ID contract failed')
            response=client.post('/api/admin/orders/1/rework',auth=('coordinator','docs-only-password'),
                                 headers={'X-Requested-With':'kitchen-control'},json={'rework_actual':'85000.00'})
            if response.status_code!=200 or response.json()['economy']['actual']['margin_income']!=25000:
                issues.append('Admin example failed')
            ignored={'update_id':123456789,'message':{'from':{'id':1001},'chat':{'id':-1001,'type':'group'},'text':'/tasks'}}
            headers={'X-Telegram-Bot-Api-Secret-Token':'docs-only-secret'}
            if client.post('/telegram/webhook',headers=headers,json=ignored).json()!={'ok':True,'ignored':True}:
                issues.append('Webhook ignored example failed')
            if client.post('/telegram/webhook',headers=headers,json=ignored).json()!={'ok':True,'duplicate':True}:
                issues.append('Webhook duplicate example failed')
    report={'result':'FAIL' if issues else 'PASS','markdown_files':len(files),'relative_links':links,
            'declared_routes':len(routes),'database_tables':len(tables),'environment_variables':len(env),
            'unittest_methods_in_source':test_count,'issues':issues,
            'scope':'local links; JSON/Python example syntax; routes/tables/env/service values; CLI help; isolated API/seed examples',
            'not_executed':['production restore/reset/deploy commands','new live Telegram client E2E']}
    (ROOT/'artifacts/documentation-review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    raise SystemExit(bool(issues))


if __name__=='__main__':main()
