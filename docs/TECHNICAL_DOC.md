# WorkSense AI — Documentación Técnica

Ver el artefacto de documentación completa en el panel de artefactos de Kiro.

## Resumen de Implementación

### Backend (Python/FastAPI)
- 20+ modelos de base de datos (SQLAlchemy)
- API REST completa con 50+ endpoints
- Autenticación JWT con refresh
- Pipeline de ML: Random Forest, Gradient Boosting, Isolation Forest, XGBoost
- WebSocket con heartbeat, reconexión y eventos versionados
- 37 pruebas automatizadas (todas pasan)

### Frontend (Angular 19)
- 9 pantallas: login, dashboard, tareas, autorreportes, análisis IA, recomendaciones, sesiones, configuración, admin
- Angular Material 19 con tema cálido (rosado-turquesa)
- ECharts para visualización
- WebSocket con reconexión automática y backoff exponencial
- Build exitoso

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

### Modelos ML Entrenados (DEMO)
- Fatiga (Random Forest): Precision 98%, Recall 100%, F1 99%, ROC-AUC 100%
- Rendimiento (Gradient Boosting): MAE 0.031, R² 0.845
- Anomalías (Isolation Forest): Funcional
