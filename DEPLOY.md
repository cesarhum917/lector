# Publicar el lector en internet (GitHub Pages)

Costo total: **$0**. Solo pagas los tokens de Claude (~$2–3 USD/mes).

---

## Antes de empezar: qué queda público y qué no

| | ¿Público? |
|---|---|
| La página (`index.html`) | **Sí.** Siempre. Aun con plan de paga. Son titulares y enlaces: no pasa nada. |
| El código (`lector.py`, `fuentes.yaml`) | **Sí**, en plan gratuito. El repo tiene que ser público. |
| Tu llave de API | **NO.** Va en Secrets. Nunca se imprime ni se expone. |
| Tu perfil de negocio (COTLÉ/IBP) | **NO.** Ahora va en Secrets, fuera del código. |

La URL será algo como `https://tuusuario.github.io/lector/`. Es pública pero
nadie la va a adivinar. Si quieres el código privado, necesitas GitHub Pro (~$4/mes);
la página seguiría siendo pública de todas formas.

---

## Paso 1 — Guarda tu perfil localmente

Antes estaba escrito dentro de `lector.py`. Ahora se lee del entorno.
Agrégalo a tu `~/.zshrc` (una sola vez):

```bash
cat >> ~/.zshrc <<'EOF'
export PERFIL_LECTOR="Soy César. Dirijo IBP/COTLÉ (miel de pureza demostrable, Amazon México, exportación) y Hermas (capacitación). Vivo en Toluca/Metepec. Me interesa a fondo: adulteración y autenticidad de la miel, regulación alimentaria (SENASICA, COFEPRIS, NOM-051), Amazon y ecommerce, economía de México, IA, cine de autor, literatura y periodismo de investigación."
EOF
source ~/.zshrc
```

Verifica que quedó:

```bash
echo $PERFIL_LECTOR
python lector.py    # debe seguir puntuando igual que antes
```

---

## Paso 2 — Acomoda el workflow

GitHub solo lee el workflow si está en la ruta exacta:

```bash
mkdir -p .github/workflows
mv lector.yml .github/workflows/    # si sigue suelto en la carpeta
```

Tu carpeta debe verse así:

```
lector/
├── .github/workflows/lector.yml
├── .gitignore
├── admin.py
├── diagnostico.py
├── fuentes.yaml
├── lector.py
├── lector.db
├── index.html
├── README.md
└── requirements.txt
```

---

## Paso 3 — Sube el repo

En github.com: **New repository** → nombre `lector` → **Public** → Create.
(No agregues README ni .gitignore: ya los tienes.)

Luego, en tu carpeta:

```bash
git init
git add .
git commit -m "Lector personal"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/lector.git
git push -u origin main
```

Si `git push` te pide contraseña: GitHub ya no acepta contraseñas. Usa un
**Personal Access Token** (Settings → Developer settings → Tokens) como contraseña.

---

## Paso 4 — Mete los dos secretos

En tu repo: **Settings → Secrets and variables → Actions → New repository secret**.

Crea dos, con estos nombres exactos:

| Nombre | Valor |
|---|---|
| `ANTHROPIC_API_KEY` | tu llave `sk-ant-...` |
| `PERFIL_LECTOR` | el mismo texto del Paso 1 |

---

## Paso 5 — Enciende Pages

**Settings → Pages → Source: Deploy from a branch → Branch: `main` / `/ (root)` → Save.**

En 1–2 minutos tu lector estará en:
`https://TU-USUARIO.github.io/lector/`

---

## Paso 6 — Prueba el robot

**Actions → Lector → Run workflow.** Eso lo corre a mano, sin esperar a mañana.

Si sale verde, ya quedó: **cada día a las 6:00 AM (hora del centro)** el robot
va a jalar las noticias, procesarlas con Claude, regenerar el HTML y publicarlo solo.

En el celular: abre la URL en Safari → **Compartir → Añadir a pantalla de inicio.**
Queda como app.

---

## Cómo seguir editando fuentes

El panel (`admin.py`) sigue corriendo en tu Mac. Después de editar:

```bash
python admin.py            # editas fuentes
git add fuentes.yaml
git commit -m "Actualiza fuentes"
git push                   # el robot ya usa las nuevas mañana
```

---

## Si algo falla

**El workflow sale rojo** → Actions → clic en la corrida → mira el log.
Casi siempre es la llave: revisa que el Secret se llame exacto `ANTHROPIC_API_KEY`.

**La página sale 404** → Pages tarda un par de minutos la primera vez.
Verifica que `index.html` sí esté en el repo (`git ls-files index.html`).

**El robot no hace push** → revisa que el workflow tenga `permissions: contents: write`.
Ya lo tiene, pero si tocaste el archivo, confírmalo.
