#!/usr/bin/env python3
"""Tiny live progress server for the SenseMind schematic job.

Serves a dashboard at / and the raw state at /state.
State lives in progress.json next to this file.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "progress.json")
PORT = 8791

HTML = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>SenseMind 原理图 · 实时进度</title>
<style>
:root{--bg:#0f1419;--panel:#161d26;--line:#243040;--txt:#dbe4ee;--dim:#7f8fa3;
--ok:#3fb950;--work:#d29922;--wait:#4a5568;--bad:#f85149;--accent:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font:14px/1.5 -apple-system,"PingFang SC","Helvetica Neue",sans-serif;padding:18px}
h1{font-size:16px;margin:0 0 2px;font-weight:600}
.sub{color:var(--dim);font-size:12px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px}
.phase{font-size:13px;color:var(--accent);margin-bottom:10px;font-weight:600}
.item{display:flex;align-items:flex-start;gap:9px;padding:5px 0;border-bottom:1px dashed rgba(255,255,255,.05)}
.item:last-child{border-bottom:0}
.dot{width:9px;height:9px;border-radius:50%;margin-top:6px;flex:0 0 auto;background:var(--wait)}
.ok .dot{background:var(--ok)} .work .dot{background:var(--work);box-shadow:0 0 0 4px rgba(210,153,34,.15)}
.bad .dot{background:var(--bad)}
.item .name{flex:1}
.item .note{color:var(--dim);font-size:12px;margin-left:8px}
.badge{font-size:11px;padding:1px 7px;border-radius:999px;border:1px solid var(--line);color:var(--dim)}
.log{font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim);
max-height:220px;overflow:auto;white-space:pre-wrap}
.log b{color:var(--txt);font-weight:500}
.bar{height:4px;background:var(--line);border-radius:2px;overflow:hidden;margin:10px 0 2px}
.bar>i{display:block;height:100%;background:var(--ok);transition:width .5s}
.foot{color:var(--dim);font-size:11px;display:flex;justify-content:space-between}
</style></head><body>
<h1>SenseMind_Hardware_V1 · 原理图绘制</h1>
<div class="sub" id="updated">连接中…</div>
<div class="card"><div class="phase" id="phase">—</div>
<div class="bar"><i id="bar" style="width:0%"></i></div>
<div class="foot"><span id="pct">0%</span><span id="counts"></span></div></div>
<div class="card"><div id="items"></div></div>
<div class="card"><div class="log" id="log"></div></div>
<script>
async function tick(){
  try{
    const r = await fetch('/state?t='+Date.now()); const s = await r.json();
    document.getElementById('phase').textContent = s.phase || '—';
    document.getElementById('updated').textContent = '更新于 ' + (s.updated||'') + ' · ' + (s.agent||'');
    const items = s.items||[]; const done = items.filter(i=>i.status==='ok').length;
    const pct = items.length? Math.round(done*100/items.length):0;
    document.getElementById('bar').style.width = pct+'%';
    document.getElementById('pct').textContent = pct+'%';
    document.getElementById('counts').textContent = done+'/'+items.length+' 完成';
    document.getElementById('items').innerHTML = items.map(i=>
      `<div class="item ${i.status||''}"><div class="dot"></div>
       <div class="name">${i.name}</div><div class="note">${i.note||''}</div></div>`).join('');
    document.getElementById('log').innerHTML = (s.log||[]).map(l=>`<div>${l}</div>`).join('');
  }catch(e){ document.getElementById('updated').textContent = '面板服务未连接: '+e; }
}
tick(); setInterval(tick, 1000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/state"):
            body = b"{}"
            try:
                with open(STATE, encoding="utf-8") as fh:
                    body = fh.read().encode("utf-8")
            except FileNotFoundError:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("progress panel on http://127.0.0.1:%d" % PORT, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
