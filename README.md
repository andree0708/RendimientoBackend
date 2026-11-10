# WorkSense AI — Backend

Sistema inteligente para el análisis y predicción de fatiga y rendimiento laboral mediante Inteligencia Artificial.

## Stack

- **Python 3.13** + **FastAPI**
- **SQLAlchemy 2.0** (ORM) — soporta PostgreSQL (producción) y SQLite (desarrollo)
- **Alembic** (migraciones)
- **JWT** (autenticación)
- **WebSockets** (tiempo real)
- **scikit-learn / XGBoost** (machine learning)

## Estructura

```
app/
├── core/           # Config, database, security, deps, exceptions
├── models/          # Modelos SQLAlchemy (ORM)
├── schemas/         # Modelos Pydantic (validación)
├── services/        # Lógica de negocio
├── api/routes/      # Endpoints REST + WebSocket
├── websocket/       # Connection manager
├── ai/              # Pipeline de ML (features, modelos, pipeline)
└── main.py          # Entry point de FastAPI
agent/               # Agente local de captura de métricas (Windows)
tests/               # Pruebas automatizadas
```

## Instalación

```bash
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Editar .env con tu configuración
```

## Ejecución

```bash
uvicorn app.main:app --reload
```

La API estará disponible en `http://localhost:8000`
Documentación interactiva: `http://localhost:8000/docs`

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/v1/auth/register` | Registro de usuario |
| POST | `/api/v1/auth/login` | Inicio de sesión |
| GET | `/api/v1/auth/me` | Usuario actual |
| POST | `/api/v1/sessions` | Iniciar sesión laboral |
| POST | `/api/v1/sessions/{id}/stop` | Finalizar sesión |
| POST | `/api/v1/metrics/batch` | Enviar lote de métricas |
| POST | `/api/v1/tasks` | Crear tarea |
| POST | `/api/v1/self-reports` | Registrar autorreporte |
| POST | `/api/v1/ai/train` | Entrenar modelo (admin) |
| POST | `/api/v1/ai/predict/fatigue` | Evaluar fatiga |
| POST | `/api/v1/ai/predict/performance` | Predecir rendimiento |
| WS | `/ws?token=...` | WebSocket en tiempo real |

## WebSocket

Conectar con un token JWT válido:
```
ws://localhost:8000/ws?token=<access_token>
```

Eventos: `session.started`, `metrics.batch_received`, `task.completed`,
`self_report.submitted`, `fatigue.risk_updated`, `performance.forecast_updated`,
`recommendation.created`, `notification.created`, `model.status_changed`, etc.
