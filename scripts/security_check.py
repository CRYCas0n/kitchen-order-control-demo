"""Scan tracked files, index and reachable Git history; never print credential values."""
import json
import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

from app.config import ROOT


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def forbidden(path):
    name=Path(path).name.lower()
    return (name!='.env.example' and (name=='.env' or name.startswith('.env.'))) or bool(
        re.search(r'(^|/)(data|backups|\.venv|__pycache__)/|(^|/)local-|\.(db(?:-wal|-shm)?|sqlite3?|pem|key|log|bak|pyc|tar\.gz)$',path,re.I))


def main():
    env=dotenv_values(ROOT/'.env')
    secrets=[env[k].encode() for k in ['TELEGRAM_BOT_TOKEN','TELEGRAM_WEBHOOK_SECRET','ADMIN_PASSWORD'] if env.get(k)]
    patterns=[rb'\b\d{7,12}:[A-Za-z0-9_-]{30,}\b',rb'\bgh[pousr]_[A-Za-z0-9]{25,}\b',
              rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'\bAKIA[A-Z0-9]{16}\b']
    problems=[]
    def scan(label,content):
        if any(secret in content for secret in secrets) or any(re.search(pattern,content) for pattern in patterns):
            problems.append(label+' contains a credential pattern (value withheld)')
    tracked=set(filter(None,git('ls-files','-z').decode().split('\0')))
    paths=set(filter(None,git('ls-files','--cached','--others','--exclude-standard','-z').decode().split('\0')))
    for path in filter(None,paths):
        if forbidden(path):problems.append('Forbidden tracked path: '+path)
        local=ROOT/path
        if local.exists():scan('working tree: '+path,local.read_bytes())
        if path in tracked:scan('index: '+path,git('show',':'+path))
    objects=git('rev-list','--objects','--all').decode().splitlines()
    blobs=0
    for line in objects:
        oid,_,path=line.partition(' ')
        if git('cat-file','-t',oid).strip()!=b'blob':continue
        blobs+=1
        if forbidden(path):problems.append('Forbidden history path: '+path)
        scan('history blob: '+oid+' '+path,git('cat-file','blob',oid))
    # Private local data is permitted only while actually excluded from Git.
    private=[]
    for path in ROOT.rglob('*'):
        rel=path.relative_to(ROOT).as_posix()
        if any(part in {'.git','.venv','__pycache__','node_modules'} for part in path.relative_to(ROOT).parts):continue
        if path.is_file() and forbidden(rel):
            private.append(rel)
            if subprocess.run(['git','check-ignore','-q','--',rel],cwd=ROOT).returncode!=0:
                problems.append('Private local file is not ignored: '+rel)
    report={'result':'FAIL' if problems else 'PASS','tracked_files':len(list(filter(None,paths))),
            'history_blobs_scanned':blobs,'private_local_files_ignored':len(private),'findings':problems,
            'scope':'known local credentials plus token/key patterns in tracked tree, index and all reachable history; private local paths ignored'}
    (ROOT/'artifacts/security-review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    raise SystemExit(bool(problems))


if __name__=='__main__':main()
