#!/usr/bin/env python3
"""
lector.py — Lector personal de noticias
=======================================
Pipeline:  fuentes.yaml -> autodiscovery RSS -> fetch -> SQLite (dedup)
           -> Claude (resumen + agrupacion + relevancia) -> index.html

Uso:
    python lector.py                # corrida normal
    python lector.py --sin-claude   # sin llamar a la API (gratis, para probar)
    python lector.py --dias 3       # cuantos dias mostrar en el HTML

Requiere:  export ANTHROPIC_API_KEY="sk-ant-..."
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# CONFIGURACION
# ----------------------------------------------------------------------
DB_PATH = "lector.db"
FUENTES_PATH = "fuentes.yaml"
SALIDA_HTML = "index.html"

MODELO = "claude-haiku-4-5-20251001"   # el mas barato: $1/$5 por MTok
MAX_ITEMS_POR_LOTE = 25                # items por llamada a la API
UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html;q=0.9,*/*;q=0.8",
}

# Tu perfil: Claude puntua relevancia contra esto.
# Se lee de la variable de entorno PERFIL_LECTOR para NO exponerlo en un repo
# publico. En local ponlo en tu ~/.zshrc; en GitHub, como Secret.
PERFIL_DEFAULT = """
Lector interesado en negocios y ecommerce en Mexico, regulacion alimentaria,
inteligencia artificial, cine de autor, literatura y periodismo de investigacion.
"""
PERFIL = os.environ.get("PERFIL_LECTOR", PERFIL_DEFAULT)


# ----------------------------------------------------------------------
# BASE DE DATOS
# ----------------------------------------------------------------------
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS articulos (
            id           TEXT PRIMARY KEY,   -- hash de la url
            seccion      TEXT,
            fuente       TEXT,
            titulo       TEXT,
            url          TEXT,
            extracto     TEXT,
            publicado    TEXT,               -- ISO 8601
            visto        TEXT,               -- cuando lo capturamos
            resumen      TEXT,               -- generado por Claude
            etiqueta     TEXT,
            relevancia   INTEGER DEFAULT 0,  -- 0-10
            cluster      TEXT,               -- id del grupo de duplicados
            dominio      TEXT,               -- para el icono de la fuente
            procesado    INTEGER DEFAULT 0
        )
    """)
    # Migracion suave si la base ya existia sin la columna
    cols = [r[1] for r in con.execute("PRAGMA table_info(articulos)")]
    if "dominio" not in cols:
        con.execute("ALTER TABLE articulos ADD COLUMN dominio TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pub ON articulos(publicado)")
    con.commit()
    return con


def hash_url(url: str) -> str:
    # Normaliza para que ?utm_source=... no cuente como articulo distinto
    limpia = re.sub(r"[?&](utm_[^=]+|fbclid|gclid)=[^&]*", "", url)
    limpia = limpia.rstrip("?&/")
    return hashlib.sha256(limpia.encode()).hexdigest()[:16]


# ----------------------------------------------------------------------
# AUTODESCUBRIMIENTO DE FEEDS
# ----------------------------------------------------------------------
CACHE_FEEDS = {}


def descubrir_feed(url_sitio: str) -> str | None:
    """Busca el <link rel=alternate type=application/rss+xml> del sitio.
    Asi solo necesitas la URL del sitio en fuentes.yaml, nunca la del RSS."""
    if url_sitio in CACHE_FEEDS:
        return CACHE_FEEDS[url_sitio]

    # Caso especial: canales de YouTube exponen RSS via channel_id
    if "youtube.com" in url_sitio:
        feed = _feed_youtube(url_sitio)
        CACHE_FEEDS[url_sitio] = feed
        return feed

    try:
        r = requests.get(url_sitio, headers=UA, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for tipo in ["application/rss+xml", "application/atom+xml", "application/feed+json"]:
            link = soup.find("link", rel=lambda v: v and "alternate" in v, type=tipo)
            if link and link.get("href"):
                feed = urljoin(url_sitio, link["href"])
                CACHE_FEEDS[url_sitio] = feed
                return feed
    except Exception as e:
        print(f"    ! autodiscovery fallo en {url_sitio}: {e}")

    # Plan B: convenciones comunes (WordPress, Substack, Ghost, Industry Dive...)
    sufijos = ["/feed/", "/feed", "/rss", "/rss.xml", "/index.xml", "/atom.xml",
               "/feeds/news/", "/feed.xml", "/?feed=rss2", "/rss/"]
    base = url_sitio.rstrip("/")
    # Tambien probamos la raiz del dominio, no solo la subruta
    from urllib.parse import urlparse
    p = urlparse(url_sitio)
    raiz = f"{p.scheme}://{p.netloc}"
    candidatos = [base + s for s in sufijos]
    if raiz != base:
        candidatos += [raiz + s for s in sufijos]

    for prueba in candidatos:
        try:
            r = requests.get(prueba, headers=UA, timeout=10, allow_redirects=True)
            if not r.ok:
                continue
            cabeza = r.text[:800].lower()
            if "<rss" in cabeza or "<feed" in cabeza or "<?xml" in cabeza:
                d = feedparser.parse(r.content)
                if d.entries:
                    CACHE_FEEDS[url_sitio] = prueba
                    return prueba
        except Exception:
            continue

    CACHE_FEEDS[url_sitio] = None
    return None


def _feed_youtube(url: str) -> str | None:
    """Todo canal de YouTube tiene RSS, pero requiere el channel_id."""
    try:
        r = requests.get(url, headers=UA, timeout=15)
        m = re.search(r'"channelId":"(UC[\w-]{22})"', r.text)
        if m:
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
    except Exception as e:
        print(f"    ! youtube fallo: {e}")
    return None


# ----------------------------------------------------------------------
# INGESTA
# ----------------------------------------------------------------------
def dominio_de(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def limpiar_html(texto: str, limite: int = 400) -> str:
    if not texto:
        return ""
    txt = BeautifulSoup(texto, "html.parser").get_text(" ", strip=True)
    return txt[:limite]


def fecha_de(entry) -> str:
    for campo in ("published_parsed", "updated_parsed"):
        t = getattr(entry, campo, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def ingestar(con, config) -> int:
    nuevos = 0
    ahora = datetime.now(timezone.utc).isoformat()

    for seccion in config["secciones"]:
        print(f"\n[{seccion['nombre']}]")
        for fuente in seccion["fuentes"]:
            nombre = fuente["nombre"]
            feed_url = fuente.get("feed")

            if not feed_url:
                feed_url = descubrir_feed(fuente["url"])
                if not feed_url:
                    print(f"  x {nombre}: sin feed (revisar a mano)")
                    continue

            try:
                d = feedparser.parse(feed_url, request_headers=UA)
            except Exception as e:
                print(f"  x {nombre}: {e}")
                continue

            if not d.entries:
                print(f"  x {nombre}: feed vacio")
                continue

            tope = fuente.get("max", 30)
            cuenta = 0
            for e in d.entries[:tope]:
                url = e.get("link")
                if not url:
                    continue
                aid = hash_url(url)
                extracto = limpiar_html(e.get("summary", "") or e.get("description", ""))

                # Google News: el medio real viene en <source>. Lo usamos en vez
                # de decir "Google News" en todo, y de ahi sacamos el icono.
                titulo = e.get("title", "(sin titulo)")
                etiqueta_fuente, dominio = nombre, dominio_de(url)
                src = e.get("source")
                if src and getattr(src, "get", None):
                    if src.get("title"):
                        etiqueta_fuente = src["title"]
                    if src.get("href"):
                        dominio = dominio_de(src["href"])
                    # Google News repite " - Medio" al final del titulo
                    titulo = re.sub(r"\s+-\s+[^-]+$", "", titulo).strip() or titulo

                try:
                    con.execute(
                        "INSERT INTO articulos (id, seccion, fuente, titulo, url, "
                        "extracto, publicado, visto, dominio) VALUES (?,?,?,?,?,?,?,?,?)",
                        (aid, seccion["id"], etiqueta_fuente, titulo,
                         url, extracto, fecha_de(e), ahora, dominio),
                    )
                    cuenta += 1
                    nuevos += 1
                except sqlite3.IntegrityError:
                    pass  # ya lo teniamos: dedup gratis, sin gastar API

            print(f"  + {nombre}: {cuenta} nuevos")
            con.commit()

    return nuevos


# ----------------------------------------------------------------------
# CAPA CLAUDE: resumen, agrupacion de duplicados, relevancia
# ----------------------------------------------------------------------
PROMPT = """Eres el editor de un lector de noticias personal. Este es el perfil del lector:
{perfil}

Abajo hay {n} articulos nuevos. Para cada uno:
1. "resumen": una frase en espanol, informativa y concreta (max 25 palabras).
   Nada de "el articulo habla de". Di el hecho.
2. "etiqueta": una palabra clave.
3. "relevancia": 0-10 segun el perfil. 8-10 = accion directa para su negocio.
   5-7 = util saberlo. 0-4 = ruido.
4. "cluster": si varios articulos cuentan LA MISMA noticia, dales el mismo
   identificador corto (ej. "banxico-tasa"). Si es unico, usa su propio id.

Responde SOLO con un array JSON. Sin markdown, sin explicaciones:
[{{"id":"...","resumen":"...","etiqueta":"...","relevancia":7,"cluster":"..."}}]

ARTICULOS:
{articulos}"""


def procesar_con_claude(con, config, activo=True):
    secciones_resumibles = {s["id"] for s in config["secciones"] if s.get("resumir")}
    if not secciones_resumibles:
        return

    cur = con.execute(
        "SELECT id, seccion, fuente, titulo, extracto FROM articulos "
        "WHERE procesado = 0 AND seccion IN (%s)"
        % ",".join("?" * len(secciones_resumibles)),
        tuple(secciones_resumibles),
    )
    pendientes = cur.fetchall()

    if not pendientes:
        print("\nNada nuevo que procesar con Claude.")
        return

    print(f"\nProcesando {len(pendientes)} articulos con Claude...")

    if not activo:
        print("  (--sin-claude: se marcan como procesados sin llamar a la API)")
        con.executemany("UPDATE articulos SET procesado=1, relevancia=5, cluster=id "
                        "WHERE id=?", [(p[0],) for p in pendientes])
        con.commit()
        return

    from anthropic import Anthropic
    client = Anthropic()

    for i in range(0, len(pendientes), MAX_ITEMS_POR_LOTE):
        lote = pendientes[i:i + MAX_ITEMS_POR_LOTE]
        listado = "\n".join(
            f'- id:{r[0]} | fuente:{r[2]} | titulo:{r[3]} | extracto:{(r[4] or "")[:200]}'
            for r in lote
        )
        try:
            msg = client.messages.create(
                model=MODELO,
                max_tokens=4000,
                messages=[{"role": "user", "content": PROMPT.format(
                    perfil=PERFIL, n=len(lote), articulos=listado)}],
            )
            texto = msg.content[0].text.strip()
            texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.M).strip()
            datos = json.loads(texto)

            for d in datos:
                con.execute(
                    "UPDATE articulos SET resumen=?, etiqueta=?, relevancia=?, "
                    "cluster=?, procesado=1 WHERE id=?",
                    (d.get("resumen", ""), d.get("etiqueta", ""),
                     int(d.get("relevancia", 5)), d.get("cluster", d["id"]), d["id"]),
                )
            con.commit()
            print(f"  lote {i // MAX_ITEMS_POR_LOTE + 1}: {len(datos)} listos")
            time.sleep(1)

        except Exception as e:
            print(f"  ! error en lote: {e}")
            # No los marcamos: se reintentan en la siguiente corrida
            continue

    # Lo que no se resume (long-form, cine, libros, podcasts) queda listo tal cual
    con.execute("UPDATE articulos SET procesado=1, cluster=id "
                "WHERE procesado=0 AND seccion NOT IN (%s)"
                % ",".join("?" * len(secciones_resumibles)),
                tuple(secciones_resumibles))
    con.commit()


# ----------------------------------------------------------------------
# SALIDA HTML
# ----------------------------------------------------------------------
CSS = """
:root{--bg:#0f0f10;--card:#191919;--line:#2a2a2c;--tx:#e8e6e3;--dim:#8a8a8f;--hot:#e0a83a;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:0 0 60px}
header{position:sticky;top:0;background:rgba(15,15,16,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:14px 18px;z-index:9}
h1{font-size:17px;letter-spacing:.14em;text-transform:uppercase;font-weight:600}
.meta{color:var(--dim);font-size:12px;margin-top:3px}
nav{display:flex;gap:6px;overflow-x:auto;padding:10px 18px;border-bottom:1px solid var(--line);-webkit-overflow-scrolling:touch}
nav a{color:var(--dim);text-decoration:none;font-size:12px;white-space:nowrap;padding:5px 11px;border:1px solid var(--line);border-radius:20px}
nav a:hover{color:var(--tx);border-color:var(--dim)}
main{max-width:760px;margin:0 auto;padding:0 18px}
section{margin-top:34px}
h2{font-size:12px;letter-spacing:.15em;text-transform:uppercase;color:var(--dim);padding-bottom:9px;border-bottom:1px solid var(--line);margin-bottom:6px}
article{padding:14px 0;border-bottom:1px solid var(--line)}
article a{color:var(--tx);text-decoration:none;font-weight:600;font-size:15.5px;line-height:1.4;display:block}
article a:hover{color:var(--hot)}
.sum{color:var(--dim);font-size:14px;margin-top:5px}
.tags{margin-top:7px;font-size:11px;color:var(--dim);display:flex;gap:9px;flex-wrap:wrap;align-items:center}
.src{color:var(--dim);display:inline-flex;align-items:center;gap:5px}
.ico{width:14px;height:14px;border-radius:3px;background:var(--line);flex:none}
.hot{color:var(--hot);font-weight:600}
.dupes{font-size:11px;color:var(--dim);margin-top:5px}
.dupes a{display:inline;font-weight:400;font-size:11px;color:var(--dim);text-decoration:underline}
footer{text-align:center;color:var(--dim);font-size:12px;margin-top:44px}
"""

HTML = """<!DOCTYPE html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mi Lector</title><style>{css}</style></head><body>
<header><h1>Mi Lector</h1><div class="meta">{total} historias · {fecha}</div></header>
<nav>{nav}</nav><main>{cuerpo}</main>
<footer>Generado por lector.py</footer></body></html>"""


def render(con, config, dias=2):
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    bloques, nav, total = [], [], 0

    for s in config["secciones"]:
        minimo = s.get("min_relevancia", 0)
        filas = con.execute(
            "SELECT titulo,url,fuente,resumen,etiqueta,relevancia,cluster,dominio "
            "FROM articulos WHERE seccion=? AND publicado > ? "
            "AND COALESCE(relevancia,0) >= ? "
            "ORDER BY relevancia DESC, publicado DESC",
            (s["id"], corte, minimo),
        ).fetchall()
        if not filas:
            continue

        # Agrupar duplicados: la de mayor relevancia manda, las demas van de nota
        grupos = {}
        for f in filas:
            grupos.setdefault(f[6], []).append(f)

        # Tope por fuente: evita que un medio prolifico (La Jornada) inunde la seccion
        tope_fuente = s.get("max_por_fuente")
        vistos_fuente = {}

        items = []
        for miembros in grupos.values():
            p = miembros[0]
            titulo, url, fuente, resumen, etiqueta, rel, dom = (
                p[0], p[1], p[2], p[3], p[4], p[5], p[7])

            if tope_fuente:
                n = vistos_fuente.get(fuente, 0)
                if n >= tope_fuente:
                    continue          # ya mostro sus mejores: el resto se corta
                vistos_fuente[fuente] = n + 1

            hot = ' <span class="hot">● alta</span>' if (rel or 0) >= 8 else ""
            tag = f'<span>{etiqueta}</span>' if etiqueta else ""
            sum_html = f'<div class="sum">{resumen}</div>' if resumen else ""
            ico = (f'<img class="ico" loading="lazy" alt="" '
                   f'src="https://www.google.com/s2/favicons?sz=32&domain={dom}">'
                   if dom else '<span class="ico"></span>')

            otras = ""
            if len(miembros) > 1:
                enlaces = " · ".join(
                    f'<a href="{m[1]}" target="_blank">{m[2]}</a>' for m in miembros[1:4]
                )
                otras = f'<div class="dupes">También en: {enlaces}</div>'

            items.append(
                f'<article><a href="{url}" target="_blank">{titulo}</a>{sum_html}'
                f'<div class="tags"><span class="src">{ico}{fuente}</span>{tag}{hot}</div>'
                f'{otras}</article>'
            )
            total += 1

        slug = s["id"]
        nav.append(f'<a href="#{slug}">{s["nombre"]}</a>')
        bloques.append(
            f'<section id="{slug}"><h2>{s["nombre"]} ({len(items)})</h2>{"".join(items)}</section>'
        )

    html = HTML.format(
        css=CSS,
        total=total,
        fecha=datetime.now().strftime("%d %b %Y, %H:%M"),
        nav="".join(nav),
        cuerpo="".join(bloques),
    )
    with open(SALIDA_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n-> {SALIDA_HTML} listo: {total} historias de los ultimos {dias} dias.")


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-claude", action="store_true", help="no llamar a la API")
    ap.add_argument("--dias", type=int, default=2, help="dias a mostrar en el HTML")
    ap.add_argument("--solo-render", action="store_true", help="solo regenerar el HTML")
    args = ap.parse_args()

    with open(FUENTES_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    con = init_db()

    if not args.solo_render:
        n = ingestar(con, config)
        print(f"\n{n} articulos nuevos.")
        usar_claude = not args.sin_claude and os.environ.get("ANTHROPIC_API_KEY")
        if not args.sin_claude and not usar_claude:
            print("! Falta ANTHROPIC_API_KEY. Corriendo sin Claude.")
        procesar_con_claude(con, config, activo=bool(usar_claude))

    render(con, config, dias=args.dias)
    con.close()


if __name__ == "__main__":
    main()
