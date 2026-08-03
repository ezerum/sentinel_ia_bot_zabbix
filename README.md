# Sentinel_AI_Bot

Bot de Telegram para monitoreo y operaciones de infraestructura, integrado con **Zabbix** y con un motor de análisis basado en LLM. Permite consultar el estado del monitoreo, pedir análisis/resúmenes en lenguaje natural y ejecutar acciones de remediación de forma controlada, con control de acceso por `chat_id`, confirmación explícita, restricción por administrador y auditoría de cada acción.

## Arquitectura

El proyecto está compuesto por dos servicios que corren en contenedores separados y se comunican a través de una red interna de Docker:

- **`sentinel-bot`**: bot de Telegram (polling, vía `python-telegram-bot`). Lee el estado desde Zabbix directamente (`ZabbixClient`: dashboard, hosts, alertas, ack) y usa `LLMEngine` para análisis, reportes y respuestas en lenguaje natural (`/ask`, `/analysis`, `/report`). Las acciones de remediación (`/restart`) se delegan a `sentinel-ops` mediante `OpsClient`.
- **`sentinel-ops`** (`ops_orchestrator`): servicio orquestador. Expone una API interna (puerto `9000`, no publicado al host) que valida y ejecuta las acciones operativas, consultando el estado de problemas activos en Zabbix antes de actuar.

Toda interacción del bot (comandos, resultado, errores) queda registrada por `InteractionLogger` en `LOG_DIR`.

## Requisitos

- Docker y Docker Compose (v3.8+)
- Un bot de Telegram creado con [@BotFather](https://t.me/BotFather)
- Acceso a una instancia de Zabbix con API habilitada y un token de API válido
- (Opcional) Acceso a un endpoint de LLM compatible con la API de chat completions (por defecto apunta a OpenAI), si se habilita el análisis con IA

## Comandos disponibles

| Comando | Descripción |
|---|---|
| `/start` | Inicia la interacción y muestra el listado de comandos |
| `/help` | Ayuda con ejemplos de uso |
| `/dashboard` | Resumen general: hosts totales, operativos, no disponibles, deshabilitados, con alertas, problemas activos y de severidad alta/disaster |
| `/alerts [minutos]` | Alertas/problemas activos recientes (ventana configurable, ej. `/alerts 60`) |
| `/hosts` | Lista de hosts monitoreados |
| `/check <host>` | Estado detallado de un host puntual |
| `/services` | Estado de servicios críticos |
| `/ack <eventid>` | Reconoce (acknowledge) una alerta en Zabbix, ej. `/ack 192` |
| `/analysis` | Análisis de incidentes recientes (últimos 120 min) asistido por LLM |
| `/report` | Reporte de incidentes de las últimas 24h asistido por LLM |
| `/ask <pregunta>` | Consulta libre en lenguaje natural, con contexto de problemas abiertos recientes |
| `/restart <host>` | Solicita el reinicio de un host vía `sentinel-ops`. Requiere ser administrador y, salvo que esté deshabilitada, una confirmación explícita |

Solo los `chat_id` incluidos en `ALLOWED_CHAT_IDS` pueden interactuar con el bot (si la lista está vacía, no se restringe); cualquier mensaje de texto que no sea un comando reconocido es manejado por un handler de fallback.

### Flujo de `/restart`

1. Solo usuarios en `OPS_ADMIN_TELEGRAM_IDS` pueden ejecutar `/restart <host>` (si la lista está vacía, no se restringe).
2. Si `OPS_REQUIRE_CONFIRM=1` (default), el bot pide confirmación explícita por chat: `CONFIRM RESTART <host>`, válida por `OPS_CONFIRM_TTL_S` segundos (default 60).
3. Al confirmar (o directamente si la confirmación está deshabilitada), el bot llama a `sentinel-ops` (`call_action("restart_host", host, actor, motivo)`), que valida la acción contra `OPS_ALLOWED_ACTIONS` y la severidad/problema activo en Zabbix antes de ejecutarla, y devuelve un `request_id`.
4. Todo el flujo (solicitud, pendiente, confirmación, error, denegado) queda registrado en el log de interacciones y en la auditoría de `sentinel-ops`.

## Variables de entorno

### `sentinel-bot`

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Sí | — | Token del bot provisto por BotFather |
| `ALLOWED_CHAT_IDS` | No | (vacío = sin restricción) | Lista de `chat_id` de Telegram autorizados, separados por coma |
| `ZABBIX_URL` | Sí | — | URL de la API de Zabbix |
| `ZABBIX_API_TOKEN` | Sí | — | Token de autenticación contra la API de Zabbix |
| `LOG_LEVEL` | No | `INFO` | Nivel de logging |
| `LOG_DIR` | No | `logs` | Directorio de logs de la app y de interacciones |
| `LLM_ENABLED` | No | `0` | Habilita el motor de análisis LLM (`1` = habilitado) |
| `LLM_ENDPOINT` | No | `https://api.openai.com/v1/chat/completions` | Endpoint del servicio LLM |
| `LLM_API_KEY` | No | — | API key para el servicio LLM |
| `LLM_MODEL` | No | `gpt-4o-mini` | Modelo a utilizar |
| `LLM_TIMEOUT_S` | No | `25` | Timeout (segundos) para las llamadas al LLM |
| `LLM_MAX_OUTPUT_TOKENS` | No | `350` | Límite de tokens de salida del LLM |
| `LLM_MAX_CHARS` | No | `4500` | Límite de caracteres de entrada/salida |
| `LLM_CACHE_TTL_S` | No | `900` | TTL (segundos) de la caché de respuestas del LLM |
| `LLM_RATE_LIMIT_PER_MIN` | No | `6` | Límite de llamadas al LLM por minuto |
| `OPS_API_URL` | No | `http://sentinel-ops:9000` | URL interna del servicio `sentinel-ops` |
| `OPS_API_KEY` | No | — | Debe coincidir con el `OPS_API_KEY` de `sentinel-ops` |
| `OPS_ADMIN_TELEGRAM_IDS` | No | (vacío = sin restricción) | `user_id` de Telegram autorizados a ejecutar/confirmar `/restart` |
| `OPS_REQUIRE_CONFIRM` | No | `1` | Si está en `1`, exige confirmación `CONFIRM RESTART <host>` antes de reiniciar |
| `OPS_CONFIRM_TTL_S` | No | `60` | Vigencia (segundos) de la confirmación pendiente |

### `sentinel-ops` 

| Variable | Descripción |
|---|---|
| `OPS_API_KEY` | Clave de autenticación entre `sentinel-bot` y `sentinel-ops` |
| `OPS_ALLOWED_ACTIONS` | Lista de acciones permitidas (whitelist), debe incluir `restart_host` para que `/restart` funcione |
| `OPS_REQUIRE_ACTIVE_PROBLEM` | Si `true`, solo permite ejecutar acciones cuando hay un problema activo asociado en Zabbix |
| `OPS_MIN_SEVERITY` | Severidad mínima de Zabbix requerida para habilitar una acción |
| `OPS_PROBLEM_LOOKBACK_MIN` | Ventana de tiempo (en minutos) hacia atrás para considerar un problema como "activo" |
| `OPS_ZABBIX_URL` | URL de la API de Zabbix |
| `OPS_ZABBIX_API_TOKEN` | Token de autenticación contra la API de Zabbix |


## Instalación y uso

```bash
git clone https://github.com/ezerum/sentinel_ia_bot.git
cd sentinel_ia_bot
cp .env.example .env  
docker compose up -d --build
```

Para ver los logs de cada servicio:

```bash
docker compose logs -f sentinel-ops
docker compose logs -f sentinel-bot
```

## Auditoría

- `sentinel-ops` registra todas las acciones ejecutadas en `./ops_logs/ops_audit.jsonl` (montado como volumen), una línea JSON por evento.
- `sentinel-bot` registra cada interacción (comando, chat, usuario, resultado, error) vía `InteractionLogger` en `LOG_DIR`.

## Seguridad

- La comunicación entre `sentinel-bot` y `sentinel-ops` se autentica mediante `OPS_API_KEY`.
- `sentinel-ops` no expone su puerto al host (`expose`, no `ports`), solo es accesible dentro de la red interna `sentinel_net`.
- El acceso al bot está restringido por `ALLOWED_CHAT_IDS`; los reinicios además requieren pertenecer a `OPS_ADMIN_TELEGRAM_IDS` y, por defecto, confirmación explícita (`OPS_REQUIRE_CONFIRM`).
- Las acciones ejecutables están limitadas por `OPS_ALLOWED_ACTIONS` y opcionalmente condicionadas a la existencia de un problema activo en Zabbix (`OPS_REQUIRE_ACTIVE_PROBLEM`, `OPS_MIN_SEVERITY`).
