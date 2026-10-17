# Fase 4: contenedor y despliegue

## Modelo y metadatos en la imagen

Se eligio empaquetar en el repositorio y en la imagen solo los dos artefactos
necesarios para inferencia:

- `models/wildfire_real.joblib` (402.371 bytes).
- `reports/real_metrics.json` (metadatos, features, umbral y resultados).

Son archivos pequenos, reproducibles y generados por este proyecto. Esta
opcion evita depender de un volumen local, un registro externo de modelos o una
descarga de artefactos en tiempo de arranque. `.gitignore` mantiene ignorados
los modelos restantes y los datos. `Dockerfile` copia solamente codigo, web,
modelo y metadatos. `.dockerignore` excluye expresamente `.env`, `data/raw/`,
`data/processed/` y caches; los datos crudos no forman parte de la imagen,
Git ni de la carga de despliegue.

## Build y prueba local observados

Con Docker Desktop activo:

```powershell
docker compose config --quiet
docker compose up -d
```

Ambos comandos terminaron con codigo 0. Compose creo y arranco el servicio
`api`. Se hizo build multi-stage de `python:3.11-slim`; Docker informo
`Successfully installed` para las dependencias y exporto la imagen
`wildfire-risk-mlops:latest` sin errores. El contenedor usa usuario no
privilegiado y healthcheck HTTP. Compose publica el puerto local 8000 hacia
7860 y aplica su propio healthcheck.

Cliente `requests` contra `http://127.0.0.1:8000`:

| Ruta | Resultado observado |
| --- | --- |
| `GET /health` | HTTP 200, `status=ok`, `model_loaded=true` |
| `GET /model-info` | HTTP 200, XGBoost real, periodo 2024-11-11–2026-10-10 |
| `POST /predict` | HTTP 200; celda `r013_c007`, fecha 2026-10-10, probabilidad `0.0714573`, umbral `0.6532685`, clase `false` |
| `GET /openapi.json` | HTTP 200, incluye `/health`, `/model-info`, `/predict` |
| `GET /` | HTTP 200, frontend identificado |

Inspeccion dentro del contenedor confirmo que `.env`, `data/raw`,
`data/processed` no existen, mientras que `models/wildfire_real.joblib` y
`reports/real_metrics.json` si existen. Respuestas observadas y verificacion
de contenido: `reports/docker_http_evidence.json`. La exclusion tambien esta
aplicada en `.gitignore`; `git ls-files data/raw .env` no encontro archivos
sensibles versionados.

## Plataforma gratuita y requisitos externos

Recomendacion: Hugging Face Spaces con Docker / CPU Basic. Encaja con el
Dockerfile y el modelo pequeno; es adecuado para una demostracion gratuita,
pero puede dormir o estar sujeto a cuotas, sin SLA ni aptitud para alertas
operativas.

Para el despliegue remoto, el propietario debe crear una cuenta Hugging Face y
un Space publico de tipo Docker, y configurar en GitHub Actions:

- Secret `HF_TOKEN`: token Hugging Face con permiso de escritura al Space.
- Variable `HF_SPACE`: `usuario/nombre-del-space`.
- Secret `MAP_KEY`: clave FIRMS, necesaria solo para `data_update.yml`.

El workflow CD publica una allow-list y hace smoke test a `/health`. La carga
no incluye `.env`, datos crudos, dataset procesado, caches ni claves. El
despliegue externo y su smoke test aun no se ejecutaron: este entorno no tiene
configurados `HF_TOKEN` ni `HF_SPACE`. No compartas los tokens por chat.
