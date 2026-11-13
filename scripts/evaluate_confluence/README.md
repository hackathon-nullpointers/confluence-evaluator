# Algoritmo de evaluación de páginas

Este documento describe cómo el paquete `scripts.evaluate_confluence` convierte
la información obtenida de Confluence en siete puntajes de criterio y una nota
ponderada diaria por página. Se basa en la implementación actual; los pesos,
umbrales y rúbricas son los definidos en [`constants.py`](./constants.py) y
[`scoring.py`](./scoring.py).

La nota es una medición reproducible de las reglas descritas aquí, no una
garantía de que una página sea correcta o adecuada para todo uso. Los criterios
de estructura y comentarios dependen de una clasificación de IA; el resultado
puede variar según el modelo y su respuesta.

## Resumen del proceso

Se excluyen los espacios personales (tipo `personal` o clave que empieza por
`~`) y sus páginas antes de recopilar contenido, evaluar o persistir resultados.
El resumen de ejecución indica cuántos espacios personales se excluyeron.
Los registros históricos que ya existen en la base no se eliminan.

```mermaid
flowchart TD
    A[Iniciar evaluación] --> B[Consultar espacios y páginas actuales]
    B --> C[Por cada página: recopilar autor, versión y contenido]
    C --> D[Extraer texto, estructura y enlaces]
    D --> E[Obtener comentarios, likes, ortografía y estado de enlaces]
    E --> F{¿Falló la recopilación?}
    F -- Sí --> X[Registrar página fallida; no calcular nota]
    F -- No --> G[Copilot clasifica estructura, dominio y tipo]
    G --> H[Copilot clasifica comentarios por lotes]
    H --> I{¿Falló la evaluación IA?}
    I -- Sí --> X
    I -- No --> J[Asignar grupo comparable de likes]
    J --> K[Calcular percentil de likes y los 7 puntajes]
    K --> L[Aplicar pesos y obtener total de 0 a 100]
    L --> M{¿Puntaje menor que 75?}
    M -- Sí --> N[Copilot explica el resultado y recomienda mejoras]
    M -- No --> O[No requiere ticket Jira]
    N --> P[Mostrar resultado y persistir evaluación]
    O --> P
    P --> Q[En ejecución normal: crear o actualizar Task para resultados bajo 75]
    X --> P
```

La recopilación y el análisis se hacen por página. Los fallos de una página no
detienen la evaluación de las demás. Las páginas fallidas se guardan con estado
`failed` y un mensaje de error, pero sin puntaje total. La ejecución termina con
código de error si hubo al menos una página fallida.

Para páginas con puntaje menor que 75, Copilot genera una explicación basada en
los criterios, pesos y mediciones, además de insights y recomendaciones concretas.
En ejecución normal, cada página bajo el umbral genera un `Task` en el proyecto
configurado por `JIRA_PROJECT_KEY`. Una etiqueta con el ID de página y la fecha hace que una
reejecución actualice el mismo issue en vez de duplicarlo. Si Jira falla para
una página, se reporta el error, se continúa con las demás y la ejecución termina
con código de error. `--dry-run` genera el feedback, pero no escribe en PostgreSQL
ni en Jira.

## Puntajes y pesos

Cada criterio produce un valor entre 0 y 100. El total se calcula con:

```text
total_score =
    author_exists_score * 0.05
  + comments_score      * 0.05
  + freshness_score     * 0.15
  + structure_score     * 0.35
  + likes_score         * 0.05
  + spelling_score      * 0.20
  + links_score         * 0.15
```

Los pesos suman 100 %. `weighted_total` comprueba que estén presentes todos los
puntajes y que cada uno se encuentre entre 0 y 100; redondea el resultado final
a dos decimales. Los puntajes de criterio se conservan con sus mediciones en
`page_evaluations`.

Ejemplo:

| Criterio | Puntaje | Peso | Aporte |
| --- | ---: | ---: | ---: |
| Autor | 100 | 5 % | 5,00 |
| Comentarios | 75 | 5 % | 3,75 |
| Actualización | 50 | 15 % | 7,50 |
| Estructura | 80 | 35 % | 28,00 |
| Likes | 75 | 5 % | 3,75 |
| Ortografía | 90 | 20 % | 18,00 |
| Enlaces | 100 | 15 % | 15,00 |
| **Total** |  | **100 %** | **81,00** |

## Criterios en detalle

### 1. Autor identificado — peso 5 %

```text
author_exists_score = 100 si hay author_account_id; de lo contrario, 0
```

El criterio mide si Confluence proporciona un ID de cuenta para el autor. No
comprueba que esa cuenta siga activa ni usa el nombre o correo para puntuar.
Estos datos se consultan aparte mediante el endpoint de usuario de Confluence y
se guardan como `author_display_name` y `author_email` cuando están disponibles.
Un perfil no visible no invalida el ID ni reduce el puntaje de autor.

### 2. Comentarios — peso 5 %

El cliente obtiene comentarios de página, tanto inline como de pie de página,
incluidas sus respuestas. Copilot evalúa cada comentario en contexto del título
de la página y devuelve:

- **Sentimiento:** `positive`, `neutral` o `negative`.
- **Relevancia:** valor de 0 a 1 sobre cuánto aporta respecto a claridad,
  exactitud, utilidad o vigencia de la página.

Las clasificaciones se procesan en lotes de hasta 15 comentarios. Cada
comentario se limita a 4.000 caracteres. La respuesta debe incluir una sola
clasificación válida para cada índice enviado; una respuesta incompleta o
inválida hace fallar la evaluación de esa página.

Se suman por separado las relevancias positivas y negativas. Los comentarios
neutrales no entran en el cálculo del puntaje:

```text
positive_relevance = suma de relevancia de comentarios positivos
negative_relevance = suma de relevancia de comentarios negativos

comments_score =
    100 * (positive_relevance + 1) / (positive_relevance + negative_relevance + 2)
```

Si no hay relevancia positiva ni negativa (por ejemplo, no hay comentarios o
todos son neutrales/irrelevantes), se asigna **50** como valor neutral. Así, la
ausencia de comentarios no se interpreta ni como aprobación ni como rechazo.
La base conserva los conteos de sentimientos y las dos sumas de relevancia.
La fórmula incorpora evidencia neutral equivalente a dos comentarios relevantes
para evitar que un único comentario positivo produzca 100. Un comentario positivo
con relevancia 1 obtiene 66,67; uno negativo obtiene 33,33. La influencia de esta
evidencia neutral disminuye al acumularse comentarios relevantes.

### 3. Fecha de actualización — peso 15 %

La fecha se toma de `version.createdAt`; si falta, se usa `updatedAt`. Se
normaliza a UTC y se compara con el instante de ejecución. Los límites son meses
calendario, no bloques fijos de 30 días:

| Antigüedad de la última actualización | Puntaje |
| --- | ---: |
| Menos de 1 mes | 100 |
| Desde 1 y menos de 3 meses | 80 |
| Desde 3 y menos de 6 meses | 60 |
| Desde 6 y menos de 12 meses | 30 |
| 12 meses o más | 0 |

La comparación de cada límite es estricta: una página actualizada exactamente
hace 1 mes obtiene 80, exactamente hace 3 meses obtiene 60, y así
sucesivamente. Una fecha futura obtiene 100.

### 4. Estructura — peso 35 %

Copilot recibe el título, clave del espacio, encabezados, cantidad de listas,
tablas, bloques de código, cantidad de palabras y texto extraído. El contenido
se limita a 24.000 caracteres; si es más extenso, se conserva el primer 75 % y
el último 25 %.

La IA asigna cinco puntajes enteros de 0 a 20:

Cada dimensión usa bandas de evidencia: 0-4 ausente, 5-9 deficiente, 10-14
parcial, 15-17 completo y 18-20 excepcional. La existencia de títulos o listas
no demuestra cobertura. Los procedimientos deben incluir prerrequisitos,
responsables, pasos ejecutables y criterios de cierre o validación. Los vacíos
relevantes impiden alcanzar el nivel completo en las dimensiones afectadas.
La rúbrica completa vive en
[`confluence-structure-analysis`](../../.github/skills/confluence-structure-analysis/SKILL.md).

| Dimensión | Qué evalúa |
| --- | --- |
| `heading_hierarchy` | Jerarquía e información de los títulos. |
| `section_coverage` | Secciones pertinentes y cobertura del tema. |
| `logical_flow` | Secuencia y organización lógica. |
| `scannability` | Facilidad de lectura mediante párrafos, listas y tablas. |
| `format_consistency` | Uso coherente del formato. |

```text
structure_score =
    heading_hierarchy
  + section_coverage
  + logical_flow
  + scannability
  + format_consistency
```

El total queda entre 0 y 100. La rúbrica indica expresamente que no se debe
penalizar la ausencia de tablas si no son necesarias. La respuesta de Copilot
también clasifica el dominio (`architecture`, `jira_governance`, `devsecops`,
`testing` o `general`) y el tipo documental (`decision_record`, `policy`,
`standard`, `procedure`, `guide`, `strategy`, `test_plan`, `reference` u
`other`); esas etiquetas se usan para agrupar likes, no se suman al puntaje de
estructura.

### 5. Likes — peso 5 %

Los likes se convierten en un percentil **relativo a páginas comparables**. La
IA etiqueta cada página por dominio y tipo documental. El grupo se asigna en
este orden:

1. `dominio:tipo` si ese grupo contiene al menos 5 páginas evaluadas con éxito.
2. `type:tipo` si no se cumple lo anterior, pero hay al menos 5 páginas de ese
   tipo en todos los dominios.
3. `global` si los grupos anteriores son demasiado pequeños.

Las páginas fallidas se excluyen al formar los grupos. Dentro de cada grupo, se
ordena conceptualmente por cantidad de likes. Los empates reciben el rango
promedio:

```text
below = cantidad de páginas del grupo con menos likes
tied  = cantidad de páginas del grupo con los mismos likes
n     = cantidad de páginas del grupo

average_zero_based_rank = below + (tied - 1) / 2
likes_score = 100 * average_zero_based_rank / (n - 1)
```

El puntaje va de 0 a 100: el mínimo de likes suele recibir 0 y el máximo 100.
Las páginas empatadas reciben el mismo resultado. Si el grupo solo tiene una
página, se asigna 50 porque no existe una comparación que permita ubicarla.

Este puntaje depende de las páginas incluidas en la corrida y de sus
clasificaciones de dominio/tipo: no representa un umbral absoluto de likes.

### 6. Ortografía — peso 20 %

El texto evaluado combina el título y el contenido legible de la página. Se
excluyen los bloques de código. Se tokenizan secuencias de letras españolas
(incluidas vocales acentuadas y `ñ`); se ignoran tokens de una sola letra. La
biblioteca `pyspellchecker` usa el diccionario español y una lista de términos
técnicos permitidos. Se pueden agregar términos mediante `SPELLING_ALLOWLIST`,
separados por comas.

```text
spelling_score =
    max(0, 100 * (1 - 5 * spelling_errors_count / word_count))
```

El puntaje mínimo es 0 y no puede ser negativo. Cada aparición de una palabra
desconocida cuenta como error, incluso si se repite. Si no hay palabras que
evaluar, el puntaje es 100. `word_count` y `spelling_errors_count` se guardan
como evidencia del cálculo.
Una tasa de errores del 5 % obtiene 75; del 10 %, 50; del 20 % o más, 0.
La lista de términos permitidos debe revisarse para evitar penalizar vocabulario
técnico válido; el corrector sigue usando español.

### 7. Enlaces válidos — peso 15 %

Se extraen enlaces de Confluence Storage y Atlas Doc Format. Las referencias
relativas se resuelven respecto a la URL de la página. Se ignoran fragmentos
locales y esquemas que no sean HTTP/HTTPS; se eliminan fragmentos URL y se
deduplican enlaces normalizados.

El comprobador revisa hasta 100 enlaces por página. Usa `HEAD` y, si el servidor
no lo admite (405/501), intenta `GET` con un rango limitado. Sigue hasta cinco
redirecciones. Un destino con respuesta HTTP 2xx o 3xx se considera válido; un
estado HTTP de error o un host inexistente, inválido. Por seguridad, puertos
distintos de 80/443 y direcciones no públicas no se consultan. Timeouts,
errores transitorios y destinos no verificables se contabilizan como no
comprobados (`unchecked`), no como enlaces rotos.

```text
total = valid_links_count + invalid_links_count + unchecked_links_count

si total > 0:
    links_score = 100 * valid_links_count / total
si total = 0:
    links_score = 50
```

Los enlaces `unchecked` entran en el denominador pero no cuentan como evidencia
válida. No se etiquetan como rotos: se conservan los tres conteos para distinguir
ausencia de verificación y fallas confirmadas. Sin enlaces se asigna 50, sin
depender del tipo documental.

## Lectura y preparación de contenido

El evaluador solicita páginas actuales y obtiene el detalle cuando la respuesta
de listado no incluye cuerpo o versión suficientes. Primero extrae Confluence
Storage y usa Atlas Doc Format como alternativa si no obtiene texto legible.
De ambas representaciones extrae texto, encabezados, listas, tablas, bloques de
código y enlaces.

La fecha y los datos del perfil del autor se obtienen de la API de Confluence.
El nombre y el correo dependen de la visibilidad del perfil; un error al
consultar el perfil se muestra como advertencia, pero no invalida el resto de
la evaluación. La comprobación de enlaces se ejecuta por separado de Copilot.

Los criterios de estructura, dominio, tipo documental y comentarios, y la
explicación del puntaje, los resuelve el agente de Copilot
[`confluence-evaluator`](../../.github/agents/confluence-evaluator.agent.md) con
tres skills en [`.github/skills/`](../../.github/skills):

| `task` enviado | Skill | Contenido |
| --- | --- | --- |
| `structure_analysis` | `confluence-structure-analysis` | Rúbrica de estructura, dominios y tipos. |
| `evaluation_feedback` | `confluence-evaluation-feedback` | Explicación, insights y recomendaciones. |
| `comment_classification` | `confluence-comment-classification` | Sentimiento y relevancia por comentario. |

Python solo envía un mensaje JSON con `task` y los datos de entrada; las
instrucciones y el formato de salida viven en el agente y las skills. La sesión
usa `custom_agents`, `skill_directories` con ruta absoluta y desactiva las demás
skills del repositorio (por ejemplo `gitbot`). La sesión aprueba los permisos de
herramientas para que el agente pueda cargar la skill; el contenido recibido se
trata como dato no confiable. Se valida que la respuesta sea JSON con categorías,
índices y campos permitidos.

Para páginas bajo 75, el servicio solicita además la explicación del puntaje y
recomendaciones.

## Fecha de referencia y versiones

La antigüedad se calcula con el instante actual en UTC cuando comienza el
cálculo. `EVALUATION_DATE`, si se configura, define el día lógico que se guarda
en la base, pero no cambia ese instante de referencia para el puntaje de
vigencia.

La base guarda `scoring_version` y `ai_prompt_version` para identificar las
reglas y el prompt que produjeron cada resultado. Si se cambian pesos,
umbrales, rúbricas o fórmulas, debe actualizarse `SCORING_VERSION`; si cambia
la instrucción enviada a Copilot (el agente o sus skills en `.github/`), debe
actualizarse `PROMPT_VERSION`. Esto
permite interpretar los puntajes históricos con la versión que los generó.
Las reglas más exigentes usan `SCORING_VERSION = v2` y la rúbrica estructural
usa `PROMPT_VERSION = v3`. Los resultados anteriores no se recalculan
automáticamente.

## Mapa de implementación

| Responsabilidad | Módulo |
| --- | --- |
| Orquestar recopilación, análisis, puntuación, Jira y reporte | [`service.py`](./service.py) |
| Contener fórmulas numéricas, percentiles y fechas | [`scoring.py`](./scoring.py) |
| Cargar el agente y sus skills, enviar tareas a Copilot y validar respuestas | [`copilot.py`](./copilot.py) |
| Instrucciones del agente y de cada tarea de IA | [`.github/agents/`](../../.github/agents) y [`.github/skills/`](../../.github/skills) |
| Crear y actualizar tickets Jira idempotentemente | [`jira.py`](./jira.py) |
| Extraer contenido de Storage y Atlas Doc Format | [`documents.py`](./documents.py) |
| Normalizar y comprobar enlaces con límites de seguridad | [`link_checker.py`](./link_checker.py) |
| Guardar evaluaciones y trazabilidad Jira en PostgreSQL | [`database.py`](./database.py) |
| Definir pesos, límites, categorías y versiones | [`constants.py`](./constants.py) |

## Persistencia y errores

El resultado se guarda en `page_evaluations`, una fila por página y
`evaluation_date`. Si se vuelve a ejecutar en la misma fecha, el proceso
actualiza la fila existente. Para cada página bajo 75, `jira_evaluation_issues`
guarda el snapshot del feedback, el proyecto, la clave/URL del issue, el estado
de sincronización, los intentos, las fechas y el último error. Consulta
[`../../db/README.md`](../../db/README.md) para el detalle de las tablas y
migraciones.

Un error no recuperable al obtener el contenido, mediciones requeridas o
resultado de IA marca esa página como fallida. No se asigna un total a páginas
fallidas ni se usan para calcular percentiles de likes. Una consulta de perfil
fallida solo genera una advertencia; un enlace no verificable se cuenta como
`unchecked`. Las otras páginas continúan. Un error de Jira no revierte la
evaluación ya guardada: se reporta y la ejecución termina con código de error.
Si falla la generación de recomendaciones, se conserva la evaluación numérica,
se reporta el error y no se crea el ticket de esa página.
En modo `--dry-run` se ejecutan las mismas consultas y evaluaciones, pero no se
escribe en PostgreSQL ni en Jira.

## Ejecución y configuración

Desde la raíz del repositorio:

```sh
python -m unittest discover -s tests -v
python -m scripts.evaluate_confluence --dry-run
```

El modo de prueba igualmente consulta Confluence, verifica enlaces externos y
envía contenido a Copilot. Configura `JIRA_PROJECT_KEY` (por defecto `KAN`). Jira reutiliza
`CONFLUENCE_BASE_URL`, `ATLASSIAN_EMAIL` y `ATLASSIAN_API_TOKEN`; la cuenta debe
tener permisos para crear y editar issues en el proyecto. El resto de variables
y credenciales requeridas se describen en [`../../README.md`](../../README.md).
