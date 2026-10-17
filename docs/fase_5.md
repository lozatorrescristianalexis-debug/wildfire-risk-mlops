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

## Corridas observadas el 17-oct-2026

- [Data update, run 39074137185](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39074137185):
  job `download-real-data` finalizado en `success`; secreto comprobado como
  configurado sin mostrar su valor; FIRMS y Open-Meteo descargados y artifact
  `real-data-update` subido (1.771.037 bytes, retencion de 14 dias). Rango
  solicitado `2024-10-10`–`2026-10-10`; dataset integrado: 43.344 filas,
  `2024-11-11`–`2026-10-10`, 2.218 positivas, 41.126 negativas y 7.206
  detecciones FIRMS retenidas. El inicio modelable posterior se debe a las
  ventanas/lags. El artifact no incluye los CSV crudos.
- [Retrain, run 39075036568](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39075036568):
  `success`; 10 trials Optuna por modelo y cuatro modelos evaluados con
  validacion temporal. El candidato seleccionado fue
  HistGradientBoosting; su F1 de validacion temporal fue `0.425635`, menor que
  el vigente `0.431636`. Resultado: **no promovido**; modelo y artefactos
  versionados permanecen sin cambios. El F1 de test del candidato fue
  `0.5090` y no se usa para decidir la promocion.
- [Monitoring, run 39075038467](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39075038467):
  `success`; comparo referencia `2026-06-13`–`2026-09-10` (9.072 filas) con
  ventana reciente `2026-09-11`–`2026-10-10` (4.032 filas). El cambio absoluto
  observado de tasa positiva fue `0.038057`; 9 features superaron PSI `0.20`.
  El reporte fue publicado como artifact `real-data-drift-report` por 30 dias.
  Es una senal para revision, no evidencia por si sola de fallo del modelo.

El run de data update completo concluyo `success` a las 22:34:45Z. El job y el
artifact habian terminado correctamente a las 22:23:46Z; la vista/API de
Actions tardo aproximadamente 11 minutos en reflejar la conclusion agregada.
La demora fue de sincronizacion del estado de Actions, no un fallo del
workflow, por lo que no se requirio corregirlo ni repetir la descarga. Los runs
manuales de retrain y monitoring tambien concluyeron `success`.
