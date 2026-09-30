"""Deploy code using an existing SSH key. Secrets are copied only to the private project directory."""
import argparse
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('target',help='user@host')
    parser.add_argument('--key',required=True)
    args=parser.parse_args()
    if args.target.startswith('-'):raise SystemExit('Invalid target')
    options=['-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15','-i',args.key]
    def remote(command):subprocess.run(['ssh',*options,args.target,command],check=True)
    remote('install -d -m 750 /opt/kitchen-control')
    with tempfile.TemporaryDirectory() as temp:
        archive=Path(temp)/'kitchen-code.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for name in ['app','static','templates','scripts','tests','deploy','docs','README.md','requirements.txt','requirements-lock.txt','.env.example','.gitignore']:
                path=ROOT/name
                if path.exists():
                    tar.add(path,arcname=name,filter=lambda info:None if '__pycache__' in info.name.split('/') else info)
        subprocess.run(['scp',*options,str(archive),args.target+':/opt/kitchen-control/code.tar.gz'],check=True)
    subprocess.run(['scp',*options,str(ROOT/'.env'),args.target+':/opt/kitchen-control/.env'],check=True)
    remote('cd /opt/kitchen-control && chmod 600 .env && tar xzf code.tar.gz && bash deploy/install.sh')


if __name__=='__main__':main()
