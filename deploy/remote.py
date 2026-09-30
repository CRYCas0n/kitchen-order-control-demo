"""Run a reviewed Python file remotely via stdin, avoiding nested shell quoting."""
import argparse
import subprocess
import sys
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('script')
parser.add_argument('--target',default='root@45.67.202.162')
parser.add_argument('--key',default=str(Path.home()/'.ssh/playlens_deploy'))
args=parser.parse_args()
result=subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15',
                       '-i',args.key,args.target,'cd /opt/kitchen-control && .venv/bin/python -'],
                      input=Path(args.script).read_bytes(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
sys.stdout.reconfigure(encoding='utf-8')
print(result.stdout.decode('utf-8','replace'))
raise SystemExit(result.returncode)
