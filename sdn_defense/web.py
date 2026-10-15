"""只读实验看板，本机可访问；支持实时日志和已完成实验回放。"""
import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from sdn_defense.report import json_lines, throughput

ASSETS = Path(__file__).resolve().parents[1] / "web"


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *a, root, **kw):
        self.root = Path(root).resolve()
        super().__init__(*a, **kw)

    def do_GET(self):
        url=urlparse(self.path)
        try:
            if url.path == "/api/runs":
                runs=[]
                for f in self.root.glob("*/*/metadata.json"):
                    try:
                        m=json.loads(f.read_text());m["path"]=str(f.parent.relative_to(self.root));runs.append(m)
                    except (OSError,json.JSONDecodeError):
                        pass
                self.send_json(sorted(runs,key=lambda r:r.get("started",0),reverse=True));return
            if url.path == "/api/results":
                f=self.root/"results.json";self.send_json(json.loads(f.read_text()) if f.exists() else {});return
            if url.path == "/api/run":
                rel=parse_qs(url.query).get("id",[""])[0]
                directory=(self.root/rel).resolve()
                if not directory.is_relative_to(self.root) or not rel:
                    self.send_error(400);return
                def read(name):
                    f=directory/name
                    return json.loads(f.read_text()) if f.exists() else {}
                self.send_json({"metadata":read("metadata.json"),"state":read("state.json"),
                    "samples":json_lines(directory/"samples.jsonl"),"events":json_lines(directory/"events.jsonl"),
                    "throughput":throughput(directory/"receiver.json")});return
            files={"/":"index.html","/app.js":"app.js","/style.css":"style.css"}
            if url.path not in files:
                self.send_error(404);return
            file=ASSETS/files[url.path]
            content=file.read_bytes()
            kind={".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8"}[file.suffix]
            self.send_response(200);self.send_header("Content-Type",kind);self.send_header("Content-Length",str(len(content)))
            self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(content)
        except (OSError,ValueError,KeyError):
            self.send_error(404,"实验数据尚不可用")

    def send_json(self,obj):
        data=json.dumps(obj,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-store")
        self.end_headers();self.wfile.write(data)

    def log_message(self,*args):
        pass


def main():
    p=argparse.ArgumentParser();p.add_argument("--root",default="artifacts");p.add_argument("--port",type=int,default=8808)
    a=p.parse_args()
    print(f"实验看板：http://127.0.0.1:{a.port}（真实日志，未产生数据时显示空状态）",flush=True)
    ThreadingHTTPServer(("127.0.0.1",a.port),partial(Handler,root=a.root)).serve_forever()


if __name__ == "__main__":main()
