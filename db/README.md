# Esquema PostgreSQL

El esquema de [`schema.sql`](./schema.sql) guarda los espacios y páginas de
Confluence que se evalúan, además del resultado histórico de cada evaluación.
Está diseñado para Confluence Cloud y usa IDs internos autoincrementales para
las relaciones, conservando también los IDs externos de Confluence.

## Relaciones

```text
confluence_spaces 1 ─── N confluence_pages 1 ─── N page_evaluations
```

- Un espacio puede tener muchas páginas.
- Cada página pertenece a un espacio.
- Una página puede tener múltiples evaluaciones históricas.
- `page_evaluations` permite una sola fila por página y día mediante la
  restricción `UNIQUE (page_id, evaluation_date)`.

## Tablas

### `confluence_spaces`

Catálogo de espacios de Confluence.

| Columna | Descripción |
| --- | --- |
| `id` | ID interno autoincremental; clave primaria. |
| `confluence_space_id` | ID externo del espacio en Confluence; único. |
| `space_key` | Clave del espacio, por ejemplo `ARQ`; única. |
| `name` | Nombre visible. |
| `confluence_status` | Estado del espacio informado por Confluence. |
| `created_at`, `updated_at` | Auditoría del registro local. |

### `confluence_pages`

Identidad y datos actuales de cada página.

| Columna | Descripción |
| --- | --- |
| `id` | ID interno autoincremental; clave primaria. |
| `confluence_page_id` | ID externo de página en Confluence; único. |
| `space_id` | Clave foránea a `confluence_spaces.id`. |
| `title` | Título actual de la página. |
| `page_url` | URL de acceso a la página. |
| `confluence_status` | Estado actual informado por Confluence. |
| `created_at`, `updated_at` | Auditoría del registro local. |

### `page_evaluations`

Una fotografía de las mediciones y puntajes de una página en el día evaluado.
Los campos de medición conservan la evidencia numérica básica; los campos
`*_score` conservan los resultados de 0 a 100 calculados por el servicio.

| Columna | Descripción |
| --- | --- |
| `evaluation_id` | ID interno autoincremental; clave primaria. |
| `page_id` | Clave foránea a `confluence_pages.id`. |
| `evaluation_date` | Día lógico de la evaluación. |
| `evaluated_at` | Instante en que se ejecutó la evaluación. |
| `author_account_id` | ID de cuenta del autor observado. |
| `author_display_name` | Nombre visible del autor obtenido de Confluence. |
| `author_email` | Correo devuelto por Confluence, sujeto a permisos y privacidad. |
| `author_exists` | Si el autor existe en Confluence. |
| `comments_analyzed_count` | Total de comentarios procesados por IA. |
| `positive_comments_count`, `neutral_comments_count`, `negative_comments_count` | Conteos por sentimiento. |
| `positive_comment_relevance`, `negative_comment_relevance` | Sumas de relevancia usadas para calcular el puntaje de comentarios. |
| `confluence_updated_at` | Última actualización de la página informada por Confluence. |
| `likes_count` | Cantidad de likes observada. |
| `word_count` | Palabras analizadas para calcular ortografía proporcionalmente. |
| `spelling_errors_count` | Errores ortográficos detectados. |
| `valid_links_count`, `invalid_links_count` | Conteos de enlaces verificados. |
| `unchecked_links_count` | Enlaces omitidos o no verificables. |
| `comparison_group` | Grupo semántico usado para comparar los likes de páginas similares. |
| `author_exists_score` | Puntaje del criterio de autor; peso 10 %. |
| `comments_score` | Puntaje del criterio de comentarios; peso 10 %. |
| `freshness_score` | Puntaje del criterio de vigencia; peso 15 %. |
| `structure_score` | Puntaje del criterio de estructura; peso 15 %. |
| `likes_score` | Puntaje del criterio de likes; peso 5 %. |
| `spelling_score` | Puntaje del criterio de ortografía; peso 20 %. |
| `links_score` | Puntaje del criterio de enlaces; peso 25 %. |
| `total_score` | Nota ponderada final, calculada por el servicio. |
| `scoring_version` | Versión de algoritmo y pesos usada para `total_score`. |
| `evaluation_status` | Estado del proceso de evaluación, gestionado por el servicio. |
| `error_message` | Error asociado a una evaluación incompleta o fallida. |
| `ai_model` | Modelo de Copilot usado para los criterios subjetivos. |
| `ai_prompt_version` | Versión del prompt de evaluación usado. |
| `created_at`, `updated_at` | Auditoría del registro local. |

Los pesos suman 100 %. El servicio calcula la nota de este modo:

```text
total_score =
    author_exists_score * 0.10
  + comments_score      * 0.10
  + freshness_score     * 0.15
  + structure_score     * 0.15
  + likes_score         * 0.05
  + spelling_score      * 0.20
  + links_score         * 0.25
```

El servicio persiste el total junto con `scoring_version` para que las
evaluaciones anteriores conserven el resultado y la versión de reglas con que
se calcularon.
La explicación detallada de cada fórmula, umbral y criterio IA está en
[`../scripts/evaluate_confluence/README.md`](../scripts/evaluate_confluence/README.md).

## Auditoría y validación

La función `set_updated_at()` y sus triggers actualizan automáticamente
`updated_at` cuando se modifica un registro de espacio, página o evaluación.
`created_at` y `updated_at` son fechas de los registros locales; no representan
las fechas originales de Confluence. Para esto último, la evaluación conserva
`confluence_updated_at`.

El esquema no contiene restricciones `CHECK`. El servicio debe validar rangos
de puntajes, conteos no negativos, estados permitidos, coherencia entre las
mediciones y puntajes, y la presencia de datos necesarios para una evaluación
completa. La base conserva claves primarias, claves foráneas y unicidad para
mantener la identidad y las relaciones.

Como solo se permite una evaluación diaria por página, una nueva ejecución el
mismo día debe decidir cómo tratar un registro existente (por ejemplo, reintento
con `UPSERT` o conservar el primero). Esta política corresponde al proceso de
evaluación.

## Crear las tablas

Desde la raíz del proyecto, con PostgreSQL disponible:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/schema.sql
```

El script crea objetos nuevos; no es una migración para una base que ya tenga
estas tablas, índices, función o triggers.

Si las tablas ya existen con el esquema anterior, aplica la migración de
[`migrations/001_add_evaluator_metrics.sql`](./migrations/001_add_evaluator_metrics.sql)
para agregar las columnas nuevas que requiere el evaluador:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f db/migrations/001_add_evaluator_metrics.sql
```

Para guardar también el nombre y correo del autor, aplica la migración:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f db/migrations/002_add_author_profile.sql
```

El correo puede estar vacío o no estar disponible según la configuración de
privacidad de la cuenta en Atlassian. El evaluador conserva el ID de cuenta y
continúa aunque no pueda recuperar los datos de perfil.
