# confluence-evaluator

## Datos para poblar Confluence

[`mock-data/spaces.json`](./mock-data/spaces.json) define cuatro espacios:
Arquitectura (`ARQ`), Gobierno Jira (`GJIRA`), DevSecOps (`DSEC`) y Testing
(`TEST`). [`mock-data/pages.json`](./mock-data/pages.json) contiene 20 páginas
de documentación en español, cinco por espacio, con contenido sustantivo en
formato Confluence Storage.

Cada elemento de `pages` contiene `spaceKey` para localizar el espacio y
`payload` con `status`, `title` y `body`. Para crear una página con la API de
Confluence Cloud, resuelve primero el ID del espacio y agrega `spaceId` al
payload. Los datos no incluyen resultados de evaluación ni pretenden asignar
metadatos que Confluence controla.

### Ejecutar la carga

El script [`scripts/populate_confluence.py`](./scripts/populate_confluence.py)
usa solo la biblioteca estándar de Python. Configura las credenciales en el
entorno local; no las incluyas en archivos ni las compartas:

```sh
export ATLASSIAN_EMAIL="tu-correo-de-atlassian"
export ATLASSIAN_API_TOKEN="tu-api-token"
```

El sitio predeterminado es `https://bcphackaton.atlassian.net`; para otro sitio,
configura `CONFLUENCE_BASE_URL`. Primero ejecuta el modo de prueba, que consulta
los espacios y páginas existentes sin escribir:

```sh
python3 scripts/populate_confluence.py
```

Si el plan es correcto, confirma la creación con:

```sh
python3 scripts/populate_confluence.py --apply
```

El script reutiliza los espacios existentes con la misma clave, crea los que
faltan y omite páginas existentes con el mismo título en el mismo espacio.
Necesita permisos para consultar/crear espacios y crear páginas. No actualiza ni
elimina contenido existente.

## Esquema inicial de evaluación

El DDL está en [`db/schema.sql`](./db/schema.sql); el modelo, las columnas, la
fórmula de ponderación y las reglas de uso se describen en
[`db/README.md`](./db/README.md). Incluye espacios, páginas y el historial de
evaluaciones diarias.

### Viabilidad y límites

Es viable crear los cuatro espacios y las 20 páginas por API. La viabilidad de
precargar todos los criterios es parcial: la API asigna como autor al usuario
autenticado, establece la fecha de actualización al crear o editar y no recibe
likes ni comentarios en el payload de creación de página. Los comentarios se
pueden intentar crear en llamadas separadas; la disponibilidad de reacciones y
los permisos requeridos dependen de la instancia.

La estructura, ortografía y enlaces quedan en el contenido de las páginas y
pueden evaluarse después de cargarlas. El inventario de integraciones incluye
un enlace `.invalid` intencionalmente no resoluble como ejemplo de referencia
rota. Las fechas reales, likes, comentarios y autores no se pueden garantizar
mediante estos archivos de creación.

## Evaluación diaria

El paquete [`scripts/evaluate_confluence/`](./scripts/evaluate_confluence/)
obtiene las páginas y espacios actuales con la API v2 de Confluence; evalúa
autor, antigüedad, ortografía y enlaces; y usa GitHub Copilot para clasificar
comentarios y evaluar estructura. Luego calcula likes por percentil dentro de
grupos de páginas similares y persiste una evaluación diaria por página. Las
reglas, pesos y columnas se describen en [`db/README.md`](./db/README.md).
La explicación paso a paso del algoritmo está en
[`scripts/evaluate_confluence/README.md`](./scripts/evaluate_confluence/README.md).

Antes de ejecutar, instala `requirements.txt` y crea las tablas de
[`db/schema.sql`](./db/schema.sql) en PostgreSQL. Si la base ya tiene las tablas
anteriores, aplica en orden las migraciones
[`001_add_evaluator_metrics.sql`](./db/migrations/001_add_evaluator_metrics.sql)
y [`002_add_author_profile.sql`](./db/migrations/002_add_author_profile.sql).
Aplica también [`003_add_jira_issue_traceability.sql`](./db/migrations/003_add_jira_issue_traceability.sql)
para registrar la trazabilidad y el feedback guardados en Jira.
El evaluador requiere Python 3.11 o posterior y estas variables:

- `ATLASSIAN_EMAIL` y `ATLASSIAN_API_TOKEN`: credenciales Atlassian para
  Confluence y Jira. La cuenta necesita permiso para crear y editar issues en
  el proyecto Jira.
- `COPILOT_GITHUB_TOKEN`: token OAuth de usuario compatible con GitHub Copilot
  SDK. Es obligatorio tanto localmente como en Actions; no uses un Personal
  Access Token, que el endpoint de Copilot rechaza.
- `DATABASE_URL`: conexión PostgreSQL (no necesaria con `--dry-run`).
- `CONFLUENCE_BASE_URL`: opcional; por defecto es
  `https://bcphackaton.atlassian.net`.
- `JIRA_PROJECT_KEY`: opcional; proyecto destino de los tickets, por defecto
  `KAN`.
- `COPILOT_MODEL`: opcional; por defecto `gpt-4.1`, disponible para la cuenta
  validada con el SDK. Define otro modelo solo si aparece disponible para tu
  cuenta y funciona con el endpoint de chat usado por Copilot SDK.
- `SPELLING_ALLOWLIST`: opcional; palabras técnicas adicionales separadas por
  comas.

Ejecuta primero las pruebas y, si quieres inspeccionar una evaluación sin
escribir en la base de datos, usa:

```sh
python -m unittest discover -s tests -v
python -m scripts.evaluate_confluence --dry-run
```

`--dry-run` todavía consulta Confluence, verifica enlaces externos y envía el
contenido de páginas y comentarios a Copilot para evaluarlos y generar
recomendaciones (mediante el agente `confluence-evaluator` y sus skills en
`.github/agents` y `.github/skills`); no persiste resultados en PostgreSQL ni crea tickets Jira.
Ejecución normal:

```sh
python -m scripts.evaluate_confluence
```

El workflow
[`evaluate-confluence.yml`](./.github/workflows/evaluate-confluence.yml)
ejecuta las pruebas y evaluación cada día a las 07:00 UTC, y también admite
ejecución manual. Configura los secretos `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`,
`COPILOT_GITHUB_TOKEN` y `DATABASE_URL` en GitHub Actions. `COPILOT_GITHUB_TOKEN`
debe ser un OAuth user access token aceptado por Copilot, no un PAT. Las
variables `CONFLUENCE_BASE_URL`, `COPILOT_MODEL` y `JIRA_PROJECT_KEY` son
opcionales.

El proceso actualiza la fila del mismo día en caso de reintento y guarda estado
fallido por página cuando no se puede completar su evaluación.