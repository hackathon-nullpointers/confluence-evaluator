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