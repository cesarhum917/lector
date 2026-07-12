# Mi Lector

Lector de noticias personal. Pipeline: `fuentes.yaml` → autodescubrimiento de RSS →
SQLite (dedup) → Claude (resumen, agrupación de duplicados, relevancia) → `index.html`.

## Correr en local

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."

python lector.py                 # corrida completa
python lector.py --sin-claude    # sin API: gratis, para probar fuentes
python lector.py --solo-render   # solo regenerar el HTML
python lector.py --dias 3        # cuántos días mostrar
```

Abre `index.html` en el navegador. En el celular: "Añadir a pantalla de inicio".

## Agregar una fuente nueva

Solo pega la URL del **sitio** (no la del RSS) en `fuentes.yaml`:

```yaml
- nombre: "Revista Nueva"
  url: "https://revistanueva.com"
```

El script descubre el feed solo. Si falla (te avisa con `x sin feed`), agrega la
URL exacta con `feed:` en lugar de `url:`.

Para un podcast: copia el enlace RSS desde tu app de podcasts y ponlo en `feed:`.

## Ajustar el comportamiento por sección

| campo | efecto |
|---|---|
| `resumir: true` | Claude resume y agrupa duplicados. Para secciones ruidosas. |
| `resumir: false` | Se lista tal cual. Para long-form, cine, libros, podcasts. |
| `ranking: true` | Ordena por relevancia contra tu perfil. |

El perfil que Claude usa para puntuar está en `PERFIL`, dentro de `lector.py`.
Edítalo cuando cambien tus prioridades.

## Publicar gratis (GitHub Pages)

1. Sube esta carpeta a un repo **privado** en GitHub.
2. Settings → Secrets and variables → Actions → New secret:
   `ANTHROPIC_API_KEY` con tu llave.
3. Settings → Pages → Source: `Deploy from a branch` → `main` / `root`.
4. El workflow corre solo cada mañana. Tu lector queda en
   `https://<tu-usuario>.github.io/<repo>/`.

Costo: GitHub Actions y Pages son gratis. Solo pagas los tokens de Claude
(~$1–3 USD/mes con Haiku).

## Costo: cómo mantenerlo bajo

- Ya usa **Haiku 4.5**, el modelo más barato ($1/$5 por millón de tokens).
- El dedup en SQLite evita pagar dos veces por el mismo artículo.
- Las secciones con `resumir: false` **nunca** tocan la API.
- Si crece mucho el volumen, sube `MAX_ITEMS_POR_LOTE` o pasa a la Batch API (50% menos).
