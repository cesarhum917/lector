#!/usr/bin/env python3
"""
admin.py — Panel local para administrar fuentes.yaml

    python admin.py          -> abre http://localhost:8000

Desde ahi puedes agregar o quitar fuentes, y ajustar el tope de noticias
por seccion. Escribe fuentes.yaml de verdad (hace respaldo antes).

La pagina publicada (index.html) sigue siendo de solo lectura: esto corre
solo en tu Mac, cuando tu lo levantas.
"""

import json
import shutil
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import yaml

RUTA = "fuentes.yaml"
PUERTO = 8000


def cargar():
    with open(RUTA, encoding="utf-8") as f:
        return yaml.safe_load(f)


def guardar(cfg):
    shutil.copy(RUTA, RUTA + ".bak")          # respaldo antes de escribir
    with open(RUTA, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=200)


PAGINA = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Fuentes</title>
<style>
:root{--bg:#0f0f10;--card:#191919;--line:#2a2a2c;--tx:#e8e6e3;--dim:#8a8a8f;--hot:#e0a83a;--bad:#e05a4d}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font:15px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;padding:26px 18px 80px}
main{max-width:760px;margin:0 auto}
h1{font-size:17px;letter-spacing:.14em;text-transform:uppercase;margin-bottom:4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:26px}
section{margin-bottom:26px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
h2{font-size:13px;letter-spacing:.09em;text-transform:uppercase;color:var(--hot);margin-bottom:4px}
.cfg{color:var(--dim);font-size:12px;margin-bottom:12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.cfg input{width:58px;background:#0f0f10;border:1px solid var(--line);color:var(--tx);border-radius:5px;padding:3px 6px;font-size:12px}
.f{display:flex;align-items:center;gap:9px;padding:8px 0;border-top:1px solid var(--line)}
.f img{width:16px;height:16px;border-radius:3px;flex:none;background:var(--line)}
.f .n{flex:1;min-width:0}
.f .n b{font-weight:600;font-size:14px;display:block}
.f .n span{color:var(--dim);font-size:11px;word-break:break-all}
button{background:none;border:1px solid var(--line);color:var(--dim);border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer;flex:none}
button:hover{color:var(--tx);border-color:var(--dim)}
.del:hover{color:var(--bad);border-color:var(--bad)}
.add{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.add input{flex:1;min-width:130px;background:#0f0f10;border:1px solid var(--line);color:var(--tx);border-radius:6px;padding:8px 10px;font-size:13px}
.add button{background:var(--hot);color:#111;border:none;font-weight:600;padding:8px 16px}
#msg{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:var(--hot);color:#111;
padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;opacity:0;transition:.2s;pointer-events:none}
#msg.on{opacity:1}
</style></head><body><main>
<h1>Fuentes</h1>
<div class="sub">Los cambios se guardan en fuentes.yaml al instante. Corre <b>python lector.py</b> para verlos reflejados.</div>
<div id="app"></div></main><div id="msg"></div>
<script>
let cfg = null;

function aviso(t){const m=document.getElementById('msg');m.textContent=t;m.classList.add('on');
  setTimeout(()=>m.classList.remove('on'),1800);}

function dom(u){try{return new URL(u).hostname.replace('www.','')}catch(e){return ''}}

async function api(accion, datos){
  const r = await fetch('/api', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({accion, ...datos})});
  cfg = await r.json();
  pintar();
}

function pintar(){
  document.getElementById('app').innerHTML = cfg.secciones.map((s,si)=>`
    <section>
      <h2>${s.nombre}</h2>
      <div class="cfg">
        <span>${s.fuentes.length} fuentes</span>
        <span>·</span>
        <label>máx. por fuente
          <input type="number" min="0" value="${s.max_por_fuente||''}" placeholder="—"
            onchange="api('config',{si:${si},campo:'max_por_fuente',valor:this.value})"></label>
        <label>relevancia mín.
          <input type="number" min="0" max="10" value="${s.min_relevancia||''}" placeholder="0"
            onchange="api('config',{si:${si},campo:'min_relevancia',valor:this.value})"></label>
      </div>
      ${s.fuentes.map((f,fi)=>{
        const u = f.feed||f.url||''; const d = dom(u);
        return `<div class="f">
          <img loading="lazy" src="https://www.google.com/s2/favicons?sz=32&domain=${d}">
          <div class="n"><b>${f.nombre}</b><span>${u}</span></div>
          <button class="del" onclick="if(confirm('¿Quitar ${f.nombre.replace(/'/g,"")}?'))api('quitar',{si:${si},fi:${fi}})">Quitar</button>
        </div>`}).join('')}
      <div class="add">
        <input placeholder="Nombre" id="n${si}">
        <input placeholder="https://sitio.com  (o la URL del RSS)" id="u${si}">
        <button onclick="agregar(${si})">Agregar</button>
      </div>
    </section>`).join('');
}

function agregar(si){
  const n = document.getElementById('n'+si).value.trim();
  const u = document.getElementById('u'+si).value.trim();
  if(!n||!u){aviso('Faltan datos');return}
  api('agregar',{si, nombre:n, url:u});
  aviso('Agregada: '+n);
}

fetch('/api',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({accion:'leer'})}).then(r=>r.json()).then(d=>{cfg=d;pintar()});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGINA.encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        d = json.loads(self.rfile.read(n) or "{}")
        cfg = cargar()
        acc = d.get("accion")

        if acc == "agregar":
            url = d["url"]
            # Si huele a feed directo, lo fijamos; si no, dejamos autodescubrimiento
            campo = "feed" if any(
                k in url.lower() for k in ("/feed", "rss", ".xml", "/atom")
            ) else "url"
            cfg["secciones"][d["si"]]["fuentes"].append(
                {"nombre": d["nombre"], campo: url})
            guardar(cfg)
            print(f"  + {d['nombre']}")

        elif acc == "quitar":
            f = cfg["secciones"][d["si"]]["fuentes"].pop(d["fi"])
            guardar(cfg)
            print(f"  - {f['nombre']}")

        elif acc == "config":
            s = cfg["secciones"][d["si"]]
            v = d["valor"]
            if v in ("", None):
                s.pop(d["campo"], None)
            else:
                s[d["campo"]] = int(v)
            guardar(cfg)
            print(f"  ~ {s['nombre']}: {d['campo']} = {v or '—'}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(cargar()).encode())


if __name__ == "__main__":
    print(f"\nPanel de fuentes -> http://localhost:{PUERTO}")
    print("Ctrl+C para salir. Se respalda en fuentes.yaml.bak antes de cada cambio.\n")
    webbrowser.open(f"http://localhost:{PUERTO}")
    HTTPServer(("localhost", PUERTO), Handler).serve_forever()
