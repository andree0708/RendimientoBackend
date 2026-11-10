# WorkSense AI — Documentación Técnica

Ver el artefacto de documentación completa en el panel de artefactos de Kiro.

## Resumen de Implementación

### Backend (Python/FastAPI)
- 20+ modelos de base de datos (SQLAlchemy)
- API REST completa con 50+ endpoints
- Autenticación JWT con refresh
- Consentimiento informado persistido (`GET/POST /api/v1/consent`) y aplicado en la ingesta: sin consentimiento vigente, `/api/v1/metrics/batch` responde `403`.
- Exportación (`GET /api/v1/privacy/export`) y borrado (`DELETE /api/v1/privacy/data`) de los datos del usuario autenticado.
- Aislamiento por usuario en sesiones y métricas (un usuario no puede leer sesiones ni métricas de otro).
- Pipeline de ML: Random Forest, Gradient Boosting, Isolation Forest, XGBoost
- WebSocket con heartbeat, reconexión y eventos versionados
- 93 pruebas automatizadas (todas pasan; `DATABASE_URL='sqlite:///./test_worksense.db'`)

### Frontend (Angular 19)
- 9 pantallas: login, dashboard, tareas, autorreportes, análisis IA, recomendaciones, sesiones, configuración, admin
- Angular Material 19 con tema cálido (rosado-turquesa)
- ECharts para visualización
- WebSocket con reconexión automática y backoff exponencial; en producción la URL relativa `/ws` se resuelve contra el origen actual (`wss://` bajo HTTPS)
- Sin datos de demostración en la UI: el dashboard muestra estados vacíos honestos y el gráfico de actividad usa únicamente métricas reales de la sesión activa
- Acciones de configuración conectadas a la API real (perfil, consentimiento, exportación y borrado); los errores se muestran al usuario en lugar de simular éxito
- Build de producción y 2 pruebas de frontend correctos

### Agente Local (Python)
- Captura de métricas para Windows con psutil
- Privacy-first: nunca recopila pulsaciones, contenido ni capturas
- Buffer local ante pérdida de conexión
- CLI interactivo

### Infraestructura
- Docker Compose con PostgreSQL, backend y frontend
- Dockerfiles para ambos repos
- Variables de entorno (.env.example)
- Health checks

### Modelos ML (DEMO — sin evidencia científica)
- Los datos DEMO son sintéticos y **no** constituyen evidencia científica.
- Fatiga (clasificación): validación cruzada agrupada por usuario (5 folds), con features calculadas solo hasta el momento del self-report. ROC-AUC ≈ 0.66 y balanced accuracy ≈ 0.51; el modelo **no se activa** (umbral ROC-AUC 0.60 **y** balanced accuracy 0.60).
- Rendimiento (regresión, target = siguiente sesión): R² ≈ -0.21; el modelo **no se activa** (umbral R² 0.0).
- Anomalías (Isolation Forest): funcional, sin etiquetas supervisadas.
- Correcciones de integridad aplicadas:
  - Se eliminaron del feature set las columnas de self-report (eran el target de fatiga) y las derivadas del target de rendimiento.
  - Las features de fatiga se truncan en el momento del self-report: no usan actividad posterior.
  - Los baselines individuales son causales (solo observaciones pasadas), sin look-ahead.
  - Solo se usan self-reports con actividad previa; no se inventan etiquetas negativas.
  - El target de rendimiento es la siguiente sesión, no la sesión actual.
  - La evaluación usa todos los folds, compara algoritmos y reporta balanced accuracy.
  - Los modelos por debajo del umbral se guardan para auditoría pero quedan `is_active=False`; la UI muestra `unknown` en lugar de una predicción no fiable.
- Conclusión: el pipeline ya no tiene fuga de target ni look-ahead, pero el dataset sintético no contiene señal aprendible para estos targets. Hacen falta datos reales y features con poder predictivo antes de presentar resultados.

## Actualización 2026-11-10 — integridad, seguridad y privacidad

### Modelos demo nunca activos
- `train_*` marca `is_demo=True` cuando los datos son sintéticos y deja `is_active=False` aunque pase el umbral de calidad.
- `_get_active_model_bundle()` rechaza bundles sin `feature_schema_version == FEATURE_SCHEMA_VERSION (v2)` y cualquier bundle demo (por métricas o por `notes`), desactivándolo en BD (`is_active=False`). Defensa en profundidad: un modelo demo nunca predice sobre usuarios reales.
- `GET /ai/models` y `GET /ai/models/{id}` son solo superusuario (exponen rutas de artefactos).
- Tests: `test_ai.py` verifica que entrenar con demo no activa; `test_ai_integrity.py` verifica rechazo de bundles legacy y demo.

### Credenciales del agente
- `agent/config.py` nunca escribe la contraseña en disco (`save()` excluye `password`, permiso 0600 donde es posible).
- La contraseña se resuelve desde `WORKSENSE_AGENT_PASSWORD` o prompt con `getpass`; `load()` migra archivos legacy con contraseña en texto plano y los reescribe sin ella.
- `agent/main.py` (`setup`, `start`, `report`, `stop`) usa `_resolve_password()`; `status` indica disponibilidad sin mostrar el secreto.
- Tests: `tests/test_agent_config.py` (3 pasan).

### Semántica de métricas (deltas por intervalo)
- Cada fila de `ActivityMetric` es un intervalo. El colector emite deltas por intervalo para pausas/tareas/errores y `app_category_seconds`; `continuous_work_seconds` es un gauge y se agrega con `max`.
- Backend (`metrics_service`) y features (`engineer_session_features`) suman deltas; no hay doble conteo.
- Tests: `test_agent_collector.py`, `test_metrics.py::test_pause_counters_are_per_interval_deltas`, `test_ai_integrity.py::test_session_features_aggregate_interval_deltas`.

### Consentimiento con scope aplicado
- Scopes válidos: `all | activity_only | app_usage_only | minimal` (validados con regex en `ConsentUpdate` y en `consent_service.set_consent`).
- `metrics_service._apply_scope()` redacta antes de almacenar: `activity_only` pone a cero app-tracking; `app_usage_only` pone a cero tareas/errores; `minimal` solo conserva `interval/active/idle/continuous`.
- `get_latest_consent()` ordena por `created_at, granted_at, withdrawn_at` desc para evitar empates de precisión de segundos en SQLite; `grant_consent` fija `created_at` en Python con microsegundos.
- Validación de ingesta: máx 500 métricas por batch, `recorded_at` no futuro (>5 min) y `active+idle <= interval+5`.
- UI (settings) expone selector de scope con ayuda; el toggle conserva el scope elegido.
- Tests: 6 nuevos en `test_metrics.py` (redacción por scope, scope inválido, batch grande, timestamp futuro, active/idle inconsistente).

### Auditoría y privacidad
- `privacy.export` y `privacy.delete` generan entradas de audit log con IP del solicitante, actor y detalle de conteos.
- `consent.updated` ya se auditaba; admin UI muestra las últimas 50 entradas (`receipt_long`).
- Tests: `test_privacy.py` (export/delete/consent auditados).

### Correcciones menores
- `task_service.update_task`: normalización UTC (`_as_utc`) para SQLite naive vs aware al completar tareas; test de `actual_seconds >= 0`.
- Borrado de datos mantiene el último consentimiento como `withdrawn` (trazabilidad) y conserva la cuenta.

### Frontend (rendimiento y honestidad)
- Rutas lazy (`loadComponent`) por página; ECharts modular (`echarts/core` + Bar/Line + Grid/Legend/Tooltip/Graphic + CanvasRenderer). Initial total ≈ 765 kB (antes 2.22 MB), sin warning de presupuesto.
- Listas (sesiones, tareas, recomendaciones) con paginación real (`shared/pagination.ts`), estados de carga (`mat-progress-bar`), error con reintento y vacíos honestos.
- Dashboard: errores con snackbar, recuperación ante `409` (sesión ya activa del agente), duración en vivo con `setInterval`, vacío de sesiones recientes.
- Admin: etiquetas `Inactive — demo data` vs `Inactive — quality gate`; texto de entrenamiento aclara que demo nunca se activa; sección de audit log.
- Suite backend: **84 passed** (`DATABASE_URL='sqlite:///./test_worksense.db' python -m pytest -q`). Frontend: `npm test` 2 SUCCESS, `npm run build --configuration production` sin warnings de bundle.

## Actualización 2026-11-10 (2) — seguridad, coherencia y operación
- `SECRET_KEY`: `get_settings()` exige secreto aleatorio ≥32 chars si `APP_ENV=production` (`app/core/config.py`); el default solo vale para dev/test.
- Passwords: registro exige ≥8 chars con letra+dígito (`app/schemas/password_policy.py`, aplicado en `RegisterRequest` y `UserCreate`); login solo exige presente para no filtrar política.
- Refresh con rotación single-use: `create_refresh_token` incluye `jti`; `refresh_access_token` revoca el `jti` usado en `revoked_refresh_tokens` y emite access+refresh nuevos (`app/models/auth.py`, `app/services/auth_service.py`, `POST /auth/refresh` devuelve ambos). Reuso → 401. Agente actualizado para guardar el refresh rotado.
- Consentimiento coherente: `self_report_service.create_report` exige consentimiento vigente (403 si no), igual que métricas.
- Auditoría ampliada: `POST /ai/train` genera `ai.train` con tipo/uso-demo/éxito; ver en `GET /admin/audit-logs`.
- Salud operativa: `GET /health/detailed` verifica DB (`SELECT 1`) y escritura en `AI_MODELS_DIR`; degradado si falla. Headers de seguridad (`nosniff`, `DENY`, `referrer-policy`, CSP) en `app/main.py`.
- Rate limiting por endpoint: bucket estricto para `/api/v1/auth/*` (`RATE_LIMIT_AUTH_PER_MINUTE=10`) y general para el resto (`RATE_LIMIT_PER_MINUTE=120`), con `Retry-After: 60` (`app/core/rate_limit.py`). `RATE_LIMIT_ENABLED=False` desactiva en tests vía fixture autouse en `tests/conftest.py` (el middleware es singleton y sus buckets se acumularían entre tests).
- Agente: buffer persistido en `~/.worksense/metrics_buffer.json` (restaura tras reinicio, respeta `max_buffer_size` y `enable_local_buffer`); refresh rotado; aviso explícito fuera de Windows; `interruptions_count` documentado como reservado (siempre 0, nunca presentado como medido).
- Infra: `docker-compose.yml` (postgres + backend + frontend nginx) en la raíz; frontend escucha en 80.
- Tests: backend **97 passed** (incluye `test_rate_limit.py`: buckets auth/api independientes y bypass con flag); frontend **5 SUCCESS** (`pagination.spec.ts` con `TestBed.createComponent` + `setInput`). Build prod: Initial total **764.98 kB**, sin warnings.

## Despliegue AWS 2026-11-10 (coexistencia gratuita en t3.micro existente)
- Sin AWS CLI instalado se instaló v2.40.0 y se validó identidad root (`sts get-caller-identity`, cuenta `532350005299`, `us-east-1`). El MCP de AWS no exponía recursos en esta sesión, así que se operó por CLI.
- Hallazgo: ya corría `i-04baf40c66b209b05` (`t3.micro`, `cafeia-demo`) con 3 contenedores; una segunda instancia 24/7 saldría de capa gratuita (~$7.50/mes). Se reutilizó la instancia (co-hosting, costo $0).
- Red: solo regla aditiva SG `sg-00950125dad7d2f8e` → TCP 8080 desde `0.0.0.0/0`. Sin IP elástica (cambiaría la IP actual de cafeia). Puertos: 80/3000/8001 cafeia, **8080 worksense**; backend worksense sin puerto público (solo red interna `ws_net`, proxy nginx `/api/`, `/ws`).
- `~/worksense`: backend slim (tar sin `.venv/.git/tests/modelos/*.db`; los 68 MB de artefactos viejos NO se subieron), frontend precompilado local (765 kB), `docker-compose.coexist.yml` (nombres/volúmenes/red propios, `mem_limit` 550m backend + 64m frontend), `backend.env` con `SECRET_KEY` aleatorio de 64 hex, `APP_ENV=production`, SQLite en volumen (`./data/worksense.db`). SQLite a propósito: 1 GB RAM no da para Postgres + ML.
- Incidente: primer build falló (`ModuleNotFoundError: app.models`) porque el patrón `--exclude='models/*'` de bsdtar también eliminó el paquete `app/models/`; se reempaquetó por staging explícito y se verificó con `tar -tf`. Rebuild OK.
- Verificación: `worksense-backend (healthy)`, `worksense-frontend Up`, cafeia intacto (3 contenedores); público `http://98.94.12.167:8080/` → 200, `/api/v1/auth/me` sin token → 401 JSON; smoke test register 201 → login 200 → me 200 → privacy-delete 200; cuenta de prueba eliminada después (login posterior → 401).

## UI 2026-11-10 (3) — marca propia, login rediseñado y cuenta demo
- El `ERR_CONNECTION_REFUSED` a `localhost:8000` no era CORS: el frontend de dev (`environment.ts`) apunta a `:8000` y el backend estaba apagado. El login ahora distingue backend apagado (`status === 0` → "Cannot reach the server…") de credenciales inválidas (`login.ts:friendlyError`).
- Marca propia: `public/logo.svg` + `public/favicon.svg` (pulso en degradado rosa→violeta→turquesa), usados en login, sidebar e `index.html` (más `theme-color` y meta description). Fuera el icono `spa`/Angular.
- Login split-screen: hero con `--ws-hero-gradient` + features (desktop, `ws-login-hero`), tarjeta centrada en móvil; botón "Try the demo account" que rellena y envía (`useDemoAccount`). Demo: `demo@worksense.ai` / `Demo1234`, creada en local (`deploy-ws/seed_demo.py`, idempotente, otorga consentimiento `all` y migra columnas nuevas a `worksense.db` viejo) y en prod vía API pública (register 201 → login 200 → consent 200 → me 200).
- Dashboard: KPIs con tiles de icono en degradado (`ws-kpi`/`ws-kpi-icon` en `styles.scss`); títulos con texto en degradado; focus ring accesible global.
- Redespliegue solo frontend (backend intacto): dist local 766.34 kB → `~/worksense/html`, rebuild imagen nginx, `up -d frontend`; verificado `Demo1234` + `ws-login-hero` en el chunk desplegado y los 5 contenedores Up.
