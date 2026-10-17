# Fase 4: contenedor y despliegue

## Modelo y metadatos en la imagen

Se eligio empaquetar en el repositorio y en la imagen solo los dos artefactos
necesarios para inferencia:

- `models/wildfire_real.joblib` (402.371 bytes).
- `reports/real_metrics.json` (metadatos, features, umbral y resultados).

Esta opcion evita depender de un volumen local, un registro externo de modelos
o una descarga en tiempo de arranque. `Dockerfile` copia codigo, web, modelo y
metadatos; `.dockerignore` excluye `.env`, `data/raw/`, `data/processed/` y
caches. El usuario del contenedor no es root y hay healthcheck HTTP.

## Build y prueba local

`docker compose config --quiet` y `docker compose up -d` terminaron con codigo
0. Se construyo la imagen multi-stage `wildfire-risk-mlops:latest`; la prueba
HTTP local obtuvo 200 en `/health`, `/model-info`, `/predict`, `/openapi.json`
y `/`. Una inspeccion dentro del contenedor verifico que el modelo y
`reports/real_metrics.json` estan presentes y `.env`, `data/raw` y
`data/processed` no existen. Evidencia: `reports/docker_http_evidence.json`.

## Despliegue y smoke test publico

La aplicacion esta desplegada por el propietario en **Render Web Service,
Docker, plan Free**, con auto-deploy desde `main`:

`https://wildfire-risk-mlops.onrender.com`

Se llamo al endpoint publico usando `requests`, timeout de lectura de 75 s,
hasta seis intentos y pausa de 10 s (la instancia respondio en el primer
intento de cada ruta):

| Solicitud | Estado | Respuesta real |
| --- | ---: | --- |
| `GET /health` | 200 | `{"status":"ok","model_loaded":true}` |
| `GET /model-info` | 200 | `model=xgboost`, `data_source=firms_open_meteo`, rango `2024-11-11`–`2026-10-10`, umbral `0.6532685160636902`; F1 `0.5164960182`, precision `0.3628129995`, recall `0.8960526316`, ROC-AUC `0.92794585`, PR-AUC `0.5110301757`, matriz `[[6828,1196],[79,681]]` |
| `POST /predict` | 200 | fila real `r013_c007`, fecha `2026-10-10`; probabilidad `0.0714572966`, umbral `0.6532685161`, `predicted_hotspot=false`, `model=xgboost` |

El cuerpo de prediccion uso las 13 features climaticas/locales de la fila real
de `data/processed/real_daily.csv`, guardado previamente en
`reports/api_http_evidence.json`. Respuestas literales y numero de intento:
`reports/render_public_smoke.json`. Esta respuesta verifica el servicio activo;
la prediccion es retrospectiva, no una alerta ni un pronostico.

## Despliegue continuo y plan Free

Render ya esta conectado a `main` y realiza auto-deploy. El workflow
`.github/workflows/cd.yml` cumple solo la funcion de smoke test despues de
cualquier push a `main` y tambien permite `workflow_dispatch`. Lee la variable
de Actions `APP_URL`, consulta en secuencia `/health`, `/model-info` y
`/predict`, valida origen real/carga del modelo/probabilidad y reintenta por
hasta 12 rondas. Cada solicitud permite 75 s de lectura y hay 10 s entre
intentos para tolerar cold starts del plan Free.

La imagen no contiene `.env`, credenciales FIRMS ni datos crudos. Para las
actualizaciones de datos en GitHub Actions, `MAP_KEY` debe estar almacenada
como secret. Ningun token de despliegue de terceros es necesario para Render
auto-deploy.
