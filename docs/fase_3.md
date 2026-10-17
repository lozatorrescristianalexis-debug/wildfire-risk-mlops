# Fase 3: API web y predicciones HTTP

## Superficie implementada

FastAPI carga al iniciar el modelo real versionado
`models/wildfire_real.joblib` y sus metadatos `reports/real_metrics.json`.
Pydantic valida el cuerpo de inferencia: id de celda, fecha ISO, las 13
features numéricas exactas del modelo y valores finitos. La API registra
predicciones con id de celda, fecha, probabilidad y umbral; no registra
credenciales ni el cuerpo meteorologico completo.

- `GET /health`: estado del servidor y modelo.
- `GET /model-info`: modelo, fuente, rango temporal, umbral, features y
  métricas de test.
- `POST /predict`: devuelve celda, fecha, probabilidad, umbral, clase y nombre
  del modelo.
- `GET /docs`: Swagger UI; `GET /openapi.json`: esquema OpenAPI.
- `GET /`: frontend estatico en ingles, con formulario de features y tabla de
  resultados con celda, fecha, probabilidad, umbral y clasificacion.

Las probabilidades son una clasificacion retrospectiva, no una alerta ni un
pronostico futuro. La interfaz no representa un mapa geografico; satisface la
visualizacion pedida con una tabla.

## Prueba HTTP local observada

Servidor iniciado con:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.wildfire.api:app --host 127.0.0.1 --port 8000
```

Un cliente `requests` llamo al servidor local usando el ultimo registro real de
`data/processed/real_daily.csv` para formar el cuerpo de `/predict`. Resultados
observados:

```text
GET /health       -> HTTP 200 {"status":"ok","model_loaded":true}
GET /model-info   -> HTTP 200; model=xgboost; data_source=firms_open_meteo;
                    period=2024-11-11..2026-10-10;
                    threshold=0.6532685160636902
GET /predict      -> HTTP 200
GET /openapi.json -> HTTP 200; paths=/health,/model-info,/predict
GET /             -> HTTP 200
```

Request real a `POST /predict` (features tomadas de la fila real
`r013_c007`, `2026-10-10`):

```json
{
  "cell_id": "r013_c007",
  "date": "2026-10-10",
  "features": {
    "temperature_2m_max_lag1": 33.3,
    "relative_humidity_2m_mean_lag1": 72.0,
    "precipitation_sum_lag1": 0.7,
    "wind_speed_10m_max_lag1": 10.1,
    "temperature_2m_max_mean_3d": 31.86666666666666,
    "temperature_2m_max_mean_7d": 32.7,
    "relative_humidity_2m_mean_mean_7d": 75.28571428571429,
    "wind_speed_10m_max_mean_7d": 12.642857142857142,
    "precipitation_sum_sum_3d": 27.1,
    "precipitation_sum_sum_7d": 29.49999999999999,
    "precipitation_sum_sum_30d": 95.5,
    "latitude": -9.9663977,
    "longitude": -70.5537387
  }
}
```

Response HTTP 200 observada:

```json
{
  "cell_id": "r013_c007",
  "date": "2026-10-10",
  "probability": 0.07145729660987854,
  "threshold": 0.6532685160636902,
  "predicted_hotspot": false,
  "model": "xgboost"
}
```

El cuerpo completo, incluyendo la respuesta real de `/model-info`, se conserva
en `reports/api_http_evidence.json`. Pruebas automatizadas verifican 422 para
features incompletas o no finitas.

## Validacion

- `.\.venv\Scripts\python.exe -m uvicorn ...` -> servidor listo en localhost.
- `requests.get/post` a `/health`, `/model-info`, `/predict`, `/openapi.json` y
  `/` -> todas las rutas respondieron HTTP 200.
- Pruebas automatizadas cubren API, Swagger, validacion y UI; el resultado final
  de pytest se documenta en fase 6.
