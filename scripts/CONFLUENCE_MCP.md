# MCP de consulta de Confluence

Servidor Python independiente del evaluador, basado en el SDK oficial `mcp`
con FastMCP. Solo expone lecturas y usa transporte `stdio`. No requiere
PostgreSQL, Jira ni un token de Copilot.

## Instalación y ejecución

Desde la raíz, con Python 3.11 o posterior:

```sh
python -m pip install -r requirements.txt
python -m scripts.confluence_mcp
```

Configura en el entorno `CONFLUENCE_BASE_URL` (dominio HTTPS del sitio),
`ATLASSIAN_EMAIL` y `ATLASSIAN_API_TOKEN`. No se carga `.env` automáticamente.
El proceso espera mensajes del cliente MCP por stdin; no es una CLI de consultas.
Los diagnósticos van a stderr para no interferir con el protocolo.

### VS Code

Integra esta entrada en `.vscode/mcp.json`. Cambia la ruta del intérprete si tu
entorno virtual tiene otro nombre; en Windows usa `.venv/Scripts/python.exe`.
No guardes tokens en el archivo: el ejemplo los solicita mediante una entrada
protegida. Tampoco agregues la configuración al control de versiones con secretos.

```json
{
  "inputs": [
    {
      "id": "confluence-token",
      "type": "promptString",
      "description": "Token API de Atlassian",
      "password": true
    }
  ],
  "servers": {
    "confluence-reader": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["-m", "scripts.confluence_mcp"],
      "cwd": "${workspaceFolder}",
      "env": {
        "CONFLUENCE_BASE_URL": "https://tu-sitio.atlassian.net",
        "ATLASSIAN_EMAIL": "tu-cuenta@example.com",
        "ATLASSIAN_API_TOKEN": "${input:confluence-token}"
      }
    }
  }
}
```

## Herramientas

### Agente consumidor en VS Code

El agente
[`confluence-reader`](../.github/agents/confluence-reader.agent.md) está
restringido a las cuatro herramientas del servidor. Busca extractos, recupera
solo páginas relevantes y responde en español con enlaces a las fuentes.
No modifica documentos ni crea tickets Jira; únicamente describe los pasos
documentados para solicitarlos.

Para usarlo:

1. Configura el servidor como en el ejemplo anterior; utiliza la entrada
   protegida para el token, no una credencial literal en el archivo.
2. Inicia `confluence-reader` desde la configuración MCP de VS Code y acepta
   la confianza solo después de revisar el código.
3. Comprueba que VS Code descubra las cuatro herramientas.
4. Selecciona el agente `confluence-reader` en el chat y formula una pregunta,
   por ejemplo: «En Pagao, resume las observaciones OWASP y cita su evidencia»
   o «Busca el procedimiento para solicitar un ambiente de desarrollo».

El nombre del servidor debe permanecer `confluence-reader` porque el agente
referencia sus herramientas con ese prefijo. Si lo cambias, actualiza también
`tools` en el archivo del agente. Este agente no se conecta automáticamente
al evaluador Python ni se selecciona mediante el JSON `task`.

### Contratos

| Herramienta | Entrada | Endpoint |
| --- | --- | --- |
| `confluence_list_spaces` | `{"limit":25,"cursor":null}` | `/wiki/api/v2/spaces` |
| `confluence_search_pages` | `{"query":"solicitud de ambiente","spaceKeys":["DEV","OPS"],"limit":10,"cursor":null}` | `/wiki/rest/api/search` |
| `confluence_get_page` | `{"pageId":"123456","format":"text"}` | `/wiki/api/v2/pages/123456?body-format=storage` |
| `confluence_get_page_children` | `{"pageId":"123456","limit":25,"cursor":null}` | `/wiki/api/v2/pages/123456/children` |

`limit` admite enteros entre 1 y 100. `pageId` es una cadena de dígitos. La
búsqueda no admite consultas vacías y limita `query` a 1.000 caracteres.
`spaceKeys` es opcional; sin restricción busca en todos los espacios accesibles.
Se incluyen espacios personales si la cuenta puede verlos.

### Respuesta de colecciones

```json
{
  "results": [],
  "nextCursor": null,
  "hasMore": false
}
```

Cada llamada solicita **un solo lote**, sin recorrer automáticamente toda la
colección. Pasa `nextCursor` como `cursor` manteniendo la misma herramienta y
los mismos parámetros (incluido `limit`). El cursor adapta los enlaces
`_links.next` o `Link` de Confluence y no permite cambiar de endpoint ni
sobrescribir CQL. Es opaco para el consumidor, no una credencial.

Los espacios devuelven ID, clave, nombre, tipo y estado. La búsqueda devuelve
ID de página, título, espacio cuando Confluence lo proporciona, URL y extracto
sin etiquetas HTML. Los hijos incluyen ID, título, ID de espacio cuando está
disponible y URL. Solo son hijos directos, no todos los descendientes.

### Búsqueda indexada

El cliente construye `type=page AND text~"consulta"` y añade
`space IN ("DEV","OPS")` cuando hay filtro. Escapa comillas y barras invertidas
de los valores. Solicita `excerpt=highlight` y `expand=content.space`.

No acepta CQL libre ni realiza búsqueda semántica. Los operadores de búsqueda
textual admitidos por Confluence pueden tener significado dentro de `query`.
La indexación de Confluence puede tardar en reflejar cambios recientes.
Los errores de sintaxis o permisos se informan como errores de herramienta.

### Contenido completo

`confluence_get_page` devuelve metadatos, URL, versión, formato, contenido y
`truncated:false`. Por defecto transforma Storage a texto mediante el extractor
existente; `format:"storage"` devuelve el HTML completo recibido. No corta el
cuerpo, aunque una página grande puede exceder el contexto del consumidor MCP.
No descarga adjuntos ni ejecuta o expande macros. Si no hay cuerpo Storage,
devuelve error; esta versión no recupera alternativamente Atlas Doc Format.

## Rendimiento y fiabilidad

- Flujo recomendado: buscar extractos, elegir páginas relevantes y recuperar
  únicamente esos cuerpos completos. Nunca descargar N páginas para buscar.
- Un cliente HTTP asíncrono compartido durante la vida del servidor reutiliza
  conexiones; máximo de cinco solicitudes simultáneas y cinco conexiones.
- Timeout de conexión de 10 segundos; las demás fases HTTP, de 30 segundos.
- Hasta tres intentos por solicitud para errores de transporte y HTTP
  429/500/502/503/504. Espera exponencial de 1 y 2 segundos, aumentada según
  `Retry-After` (segundos o fecha HTTP).
- Si `Retry-After` exige más de 30 segundos, informa el tiempo al consumidor en
  lugar de bloquearlo o reintentar antes de lo permitido.
- No reintenta 400, 401, 403 o 404. No devuelve listas vacías para ocultar fallos.
- No sigue redirecciones HTTP. La paginación se valida contra el sitio y
  endpoint originales antes de reutilizar parámetros.
- Sin caché inicial: las lecturas reflejan la API y evitan invalidación o mezcla
  de permisos. Mide latencia y volumen antes de añadirla.

## Permisos y límites de confianza

Todas las herramientas leen con **la misma cuenta técnica**. Cualquier cliente
con acceso al proceso ve lo que esa cuenta puede consultar; no hay autorización
por usuario final. No publiques este servidor como servicio remoto multiusuario
sin implementar autenticación y aislamiento por usuario.

El contenido recuperado, incluidos extractos y títulos, es dato no confiable:
el asistente consumidor no debe ejecutar instrucciones embebidas en las páginas.
La accesibilidad de una página no demuestra que sus afirmaciones sean correctas.
Las anotaciones `readOnlyHint` describen las herramientas, no sustituyen controles
de acceso de Confluence.

## Pruebas

```sh
python -m unittest tests.test_confluence_mcp -v
```

Las pruebas usan HTTP simulado: validan paginación, CQL, extracción, cuerpos sin
truncar, límites de concurrencia, errores, reintentos y esquemas de herramientas.
