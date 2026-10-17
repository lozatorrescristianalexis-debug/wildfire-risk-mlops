# Fase 5: automatizacion y monitoreo

## Workflows

- `.github/workflows/ci.yml`: Ruff, pytest con cobertura, validacion Compose y
  build Docker.
- `.github/workflows/cd.yml`: Render hace auto-deploy al recibir pushes a
  `main`; Actions espera el servicio en `APP_URL` y ejecuta smoke tests sobre
  `/health`, `/model-info` y `/predict`. Tiene timeouts/reintentos para el
  cold start del plan Free y puede ejecutarse manualmente.
- `.github/workflows/data_update.yml`: semanal o manual, exige `MAP_KEY`,
  descarga e integra exclusivamente datos reales y publica dataset procesado
  mas informes como artifact temporal (nunca los CSV crudos).
- `.github/workflows/retrain.yml`: automatico tras data update o manual con
  `data_run_id`; descarga el artifact, entrena con Optuna y solo promociona si
  mejora estrictamente el F1 temporal OOF.
- `.github/workflows/monitoring.yml`: automatico tras data update o manual con
  `data_run_id`; contrasta ventana reciente de 30 dias con 90 dias de
  referencia, genera PSI y cambio de la tasa positiva. PSI >= 0,20 indica una
  senal de revision, no diagnostico definitivo.

`src/wildfire/monitor.py` rechaza datasets sinteticos/mixtos, fechas invalidas,
features nulas y ventanas insuficientes. Los logs de inferencia no contienen
credenciales ni el vector completo de features.

## Configuracion de Actions

- Variable `APP_URL`: URL publica del servicio Render
  (`https://wildfire-risk-mlops.onrender.com`). Solo se usa para el smoke test
  CD; Render es quien construye y despliega desde `main`.
- Secret `MAP_KEY`: credencial NASA FIRMS; necesario para data update y por
  tanto para las acciones posteriores de reentrenamiento y monitoreo.

No se requieren `HF_TOKEN` ni `HF_SPACE`; el despliegue remoto ya no depende de
Hugging Face. Los secretos deben existir unicamente en GitHub Settings >
Secrets and variables > Actions.

## Validacion previa y ejecuciones actuales

CI **39072309838** y **39072336776** finalizaron `success`, incluyendo tests
con cobertura, Ruff, Compose y Docker build. El CD anterior **39072309839**
omitio el despliegue Hugging Face por falta de `HF_SPACE`/`HF_TOKEN`; fue
reemplazado por el smoke test Render descrito arriba.

El smoke test publico directo ya fue ejecutado: GET `/health`, GET
`/model-info` y POST `/predict` respondieron HTTP 200 usando la app real de
Render. Respuestas en `reports/render_public_smoke.json` y `docs/fase_4.md`.
Los run IDs y resultados de los nuevos workflow dispatch de CD, data update,
retrain y monitoring se agregaran una vez consultados en GitHub Actions; no se
declaran exitosos antes de ver su conclusion.
