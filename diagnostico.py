#!/usr/bin/env python3
"""
diagnostico.py — Caza los feeds de las fuentes que fallaron.

Prueba muchas rutas candidatas contra cada sitio y te imprime el YAML listo
para pegar en fuentes.yaml con el "feed:" explicito.

Uso:
    python diagnostico.py                 # revisa TODAS las fuentes de fuentes.yaml
    python diagnostico.py Gatopardo Forbes   # solo las que coincidan con esos nombres
"""

import sys
from urllib.parse import urljoin, urlparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, "
              "text/html;q=0.9,*/*;q=0.8",
}

SUFIJOS = [
    "/feed/", "/feed", "/rss", "/rss.xml", "/rss/", "/index.xml", "/atom.xml",
    "/feed.xml", "/?feed=rss2", "/feeds/news/", "/feeds/posts/default",
    "/blog/rss.xml", "/news/rss", "/rss/all.xml", "/en/rss",
]


def valido(url):
    """Devuelve (True, n_entradas) si la URL sirve un feed con contenido."""
    try:
        r = requests.get(url, headers=UA, timeout=12, allow_redirects=True)
        if not r.ok:
            return False, 0
        d = feedparser.parse(r.content)
        return (len(d.entries) > 0), len(d.entries)
    except Exception:
        return False, 0


def buscar(url_sitio):
    hallazgos = []

    # 1. Autodiscovery: la etiqueta <link rel="alternate"> del HTML
    try:
        r = requests.get(url_sitio, headers=UA, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.find_all("link", rel=lambda v: v and "alternate" in v):
            t = (link.get("type") or "").lower()
            if "rss" in t or "atom" in t or "xml" in t:
                href = link.get("href")
                if href:
                    hallazgos.append(urljoin(url_sitio, href))
        # 2. Cualquier <a> que apunte a algo que huela a feed
        for a in soup.find_all("a", href=True):
            h = a["href"].lower()
            if h.endswith((".xml", "/feed", "/feed/", "/rss")) and "comment" not in h:
                hallazgos.append(urljoin(url_sitio, a["href"]))
    except Exception as e:
        print(f"    (no se pudo leer el HTML: {e})")

    # 3. Rutas por convencion, sobre la subruta y sobre la raiz del dominio
    base = url_sitio.rstrip("/")
    p = urlparse(url_sitio)
    raiz = f"{p.scheme}://{p.netloc}"
    hallazgos += [base + s for s in SUFIJOS]
    if raiz != base:
        hallazgos += [raiz + s for s in SUFIJOS]

    vistos, resultados = set(), []
    for h in hallazgos:
        if h in vistos:
            continue
        vistos.add(h)
        ok, n = valido(h)
        if ok:
            resultados.append((h, n))
            if len(resultados) >= 2:
                break
    return resultados


def main():
    filtros = [a.lower() for a in sys.argv[1:]]
    config = yaml.safe_load(open("fuentes.yaml", encoding="utf-8"))

    encontrados, perdidos = [], []

    for seccion in config["secciones"]:
        for f in seccion["fuentes"]:
            if f.get("feed"):          # ya tiene feed explicito: no hay nada que buscar
                continue
            nombre = f["nombre"]
            if filtros and not any(x in nombre.lower() for x in filtros):
                continue

            print(f"\n> {nombre}  ({f['url']})")
            res = buscar(f["url"])
            if res:
                url, n = res[0]
                print(f"    OK  {url}   [{n} entradas]")
                encontrados.append((seccion["nombre"], nombre, url))
            else:
                print("    -- sin feed publico")
                perdidos.append((seccion["nombre"], nombre, f["url"]))

    print("\n" + "=" * 60)
    print("PEGA ESTO EN fuentes.yaml (reemplaza el 'url:' por el 'feed:')")
    print("=" * 60)
    for sec, nombre, url in encontrados:
        print(f'\n# [{sec}]\n      - nombre: "{nombre}"\n        feed: "{url}"')

    if perdidos:
        print("\n" + "=" * 60)
        print("SIN FEED PUBLICO (bórralas o búscalas a mano)")
        print("=" * 60)
        for sec, nombre, url in perdidos:
            print(f"  - {nombre}  [{sec}]  {url}")


if __name__ == "__main__":
    main()
