# WorkSense AI — Agente Local

Aplicación independiente para la captura de métricas laborales en Windows.

## Privacidad

El agente **NO** recopila pulsaciones de teclado, contraseñas, contenido de
mensajes, documentos, capturas de pantalla, portapapeles ni historial de
navegación. Solo recopila metadatos agregados: tiempo activo/inactivo,
frecuencia de pausas y categorías de aplicación (por nombre de proceso, nunca
por contenido).

## Instalación

```bash
# Usar el mismo entorno virtual del backend
.venv\Scripts\Activate.ps1
pip install psutil requests
```

## Uso

```bash
# Configurar (primera vez)
python -m agent.main setup

# Ver configuración
python -m agent.main status

# Iniciar captura
python -m agent.main start

# Enviar autorreporte rápido
python -m agent.main report

# Detener sesión activa
python -m agent.main stop
```

## Funcionamiento

1. El agente se autentica con el backend usando tus credenciales.
2. Inicia una sesión laboral en el backend.
3. Recopila métricas cada 60 segundos (configurable).
4. Envía lotes de métricas al backend.
5. Si no hay conexión, almacena localmente y envía al reconectar.
6. Periódicamente solicita evaluación de fatiga y predicción de rendimiento.
7. Al detenerse (Ctrl+C), finaliza la sesión correctamente.
