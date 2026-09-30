"""Serve only the static demo assets, never the project directory or secrets."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from app.config import ROOT


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/'static'),**kwargs)

    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/':self.path='/index.html'
        elif path.startswith('/static/'):self.path=path[len('/static'):]
        else:
            self.send_error(404);return
        super().do_GET()

    def list_directory(self,path):
        self.send_error(404)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8080);args=parser.parse_args()
    print(f'Open http://127.0.0.1:{args.port}; select simulation mode. No backend writes or Telegram traffic.')
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
