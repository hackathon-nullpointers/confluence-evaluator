# confluence-evaluator

## Limpieza de datos

[`scripts/cleanup_confluence.py`](./scripts/cleanup_confluence.py) elimina solo
las páginas registradas en PostgreSQL, conserva los espacios de Confluence,
elimina **todos los tickets visibles del proyecto Jira indicado** (no solo los
creados por el evaluador) y finalmente vacía las cuatro tablas del evaluador,
incluida `confluence_spaces`, conservando el esquema. Las subtareas se eliminan
antes de sus padres. No se usa `CASCADE` para vaciar tablas ajenas.

Antes de aplicar, realiza una copia de seguridad y detén el workflow del
evaluador y cualquier otro escritor de Jira, Confluence y la base. No existe
rollback distribuido: un fallo conserva la base, pero no recupera los elementos
ya eliminados de las APIs. Un error HTTP, incluido 404, detiene el proceso;
revisa los IDs ya eliminados antes de reintentar. El borrado de páginas utiliza
el comportamiento normal de Confluence (papelera), sin purga permanente.

Configura `CONFLUENCE_BASE_URL`, `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN` y
`DATABASE_URL` en el entorno; no se carga `.env` automáticamente. La cuenta debe
tener permisos de eliminación y visibilidad completa del proyecto Jira; el
script no puede descubrir tickets ocultos por permisos. No requiere Copilot.

Simulación por defecto, sin borrados:

```sh
python -m scripts.cleanup_confluence --project KAN
```

Para procesar de golpe todos los proyectos registrados en
`jira_evaluation_issues`, sin indicar cada uno:

```sh
python -m scripts.cleanup_confluence --all-tracked-projects
```

Esta opción elimina todos los tickets visibles de esos proyectos, incluso los
no creados por el evaluador; no toca proyectos ajenos al inventario. No elimina
los proyectos Jira ni los espacios Confluence. Es incompatible con `--project`.
Si no hay proyectos registrados, solo se procesan las páginas y la base.
La simulación muestra la lista de proyectos y la confirmación correspondiente:

```sh
python -m scripts.cleanup_confluence --all-tracked-projects --apply \
  --confirm "BORRAR https://tu-sitio.atlassian.net PROYECTOS-BD:ABC,KAN"
```

Sustituye el sitio y la lista ordenada por los valores exactos de la simulación.
Si el inventario de proyectos cambia, la confirmación deja de ser válida.

Solo después de revisar el inventario, aplica usando la confirmación exacta que
muestra la simulación (sustituye el dominio por el sitio real):

```sh
python -m scripts.cleanup_confluence --project KAN --apply \
  --confirm "BORRAR https://tu-sitio.atlassian.net KAN"
```

## Datos para poblar Confluence

[`mock-data/spaces.json`](./mock-data/spaces.json) define cuatro espacios:
Arquitectura (`ARQ`), Gobierno Jira (`GJIRA`), DevSecOps (`DSEC`) y Testing
(`TEST`). [`mock-data/pages-initial.json`](./mock-data/pages-initial.json)
contiene las 20 páginas iniciales de documentación en español, cinco por
espacio, y [`mock-data/pages.json`](./mock-data/pages.json) contiene cuatro
páginas adicionales (una por espacio) con los pasos y los tickets de Jira que se
deben crear para un objetivo concreto, todas con contenido sustantivo en formato
Confluence Storage. `scripts/populate_confluence.py` lee `pages.json` y omite
las páginas cuyo título ya existe en el espacio.

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