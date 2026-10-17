# Fase 8: informe tecnico para el equipo de TI

**Sistema:** Wildfire Hotspot Classifier — Madre de Dios, Peru

**Fecha de corte de esta version:** 17 de octubre de 2026

**Entorno de produccion:** Render Web Service, Docker, plan Free
**URL:** <https://wildfire-risk-mlops.onrender.com>

## 1. Resumen operativo

Servicio web/API para clasificacion retrospectiva de una celda-dia como
actividad FIRMS detectada o no detectada. La prediccion usa exclusivamente
features meteorologicas rezagadas y coordenadas. No es un pronostico de
ocurrencia, una alerta de incendios, ni un sistema de despacho o seguridad
publica.

Render realiza auto-deploy desde `main`. GitHub Actions provee CI, smoke test
post-push, ingesta semanal de datos reales, reentrenamiento condicional y
monitoreo basico de drift. La inferencia no requiere `MAP_KEY`; solo la
actualizacion de los datos a traves de FIRMS la necesita.

## 2. Arquitectura desplegada

```text
GitHub main --push--> Render build & auto-deploy
      |                         |
      +--> GitHub Actions CI    +--> FastAPI + static English UI
      +--> CD smoke tests ------------> /health, /model-info, /predict
      +--> data_update.yml --> real FIRMS + Open-Meteo --> temporary artifact
                                      |                    +--> retrain.yml
                                      |                    +--> monitoring.yml
                                      +-- never uploads raw CSVs
```

La imagen Docker multi-stage instala dependencias en builder y ejecuta el
runtime con usuario no privilegiado. Runtime contiene solo el paquete de
aplicacion, frontend, `models/wildfire_real.joblib` y
`reports/real_metrics.json`. Se verifico dentro de la imagen la ausencia de
`.env`, `data/raw/` y `data/processed/`; presencia del modelo y metadata.

## 3. API y contrato de servicio

| Metodo y ruta | Proposito | Contrato/resultados |
| --- | --- | --- |
| `GET /health` | Liveness/readiness de modelo | HTTP 200: `{"status":"ok","model_loaded":true}` |
| `GET /model-info` | Informacion de modelo | Fuente, fechas, features, threshold y metricas de test |
| `POST /predict` | Scoring de una celda-dia | `cell_id`, `date` ISO y objeto `features` con exactamente 13 variables |
| `GET /docs` | Swagger UI | OpenAPI de FastAPI |
| `GET /openapi.json` | Esquema | Describe rutas API |
| `GET /` | Aplicacion web | Interfaz inglesa y tabla de score/threshold/clase |

Pydantic restringe campos extra, identificador de celda, fecha, conjunto exacto
de features y valores finitos. La respuesta contiene `cell_id`, `date`,
`probability`, `threshold`, `predicted_hotspot` y `model`. Requests invalidos
dan 422. La API no recibe ni necesita coordenadas FIRMS brutas; latitud y
longitud forman parte de las 13 features.

Las features exactas son:

1. `temperature_2m_max_lag1`
2. `relative_humidity_2m_mean_lag1`
3. `precipitation_sum_lag1`
4. `wind_speed_10m_max_lag1`
5. `temperature_2m_max_mean_3d`
6. `temperature_2m_max_mean_7d`
7. `relative_humidity_2m_mean_mean_7d`
8. `wind_speed_10m_max_mean_7d`
9. `precipitation_sum_sum_3d`
10. `precipitation_sum_sum_7d`
11. `precipitation_sum_sum_30d`
12. `latitude`
13. `longitude`

## 4. Datos, etiquetas y modelo en produccion

- **Region:** Madre de Dios, bounding box
  `-72.4287387,-13.3413977,-68.6519906,-9.9069082`; grilla de 0,25 grados,
  144 celdas.
- **Periodo modelable:** `2024-11-11`–`2026-10-10`. El periodo solicitado de
  ingesta era `2024-10-10`–`2026-10-10`; el calentamiento de lags/ventanas
  explica el inicio posterior del dataset integrado.
- **Dataset:** 43.344 filas celda-dia; 2.218 positivas (5,1172 %) y 41.126
  negativas; 7.206 detecciones retenidas; cero nulos tras filtros.
- **Origen:** detecciones NASA FIRMS con clima diario Open-Meteo Archive. En
  la brecha `2026-07-01`–`2026-08-20` se complementaron sensores VIIRS NOAA20,
  VIIRS NOAA21 y MODIS con atribucion por producto; hubo detecciones devueltas
  en 40 de 51 dias. Once dias sin retornos no significan ausencia de fuego.
- **Etiqueta:** positiva si existe deteccion de algun sensor en celda/fecha;
  negativa solo en fecha con alguna deteccion regional, y es proxy de
  actividad/observacion satelital.
- **Modelo desplegado:** XGBoost, threshold `0.6532685160636902`. Split por
  fechas activas 80/20, holdout temporal de 8.784 filas entre 2026-08-02 y
  2026-10-10 (760 positivas, 8.024 negativas). Tuning: Optuna TPE, 10 trials
  por modelo, 3 folds temporales expansivos.

### Resultados reales del holdout

| Modelo | F1 | Precision | Recall | ROC-AUC | PR-AUC | Umbral |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Logistic baseline | 0,3485 | 0,2322 | 0,6987 | 0,8149 | 0,2016 | 0,64047 |
| Random Forest | 0,5238 | 0,3759 | 0,8632 | 0,9293 | 0,5166 | 0,37090 |
| HistGradientBoosting | 0,5090 | 0,3552 | 0,8974 | 0,9262 | 0,4806 | 0,62653 |
| XGBoost (seleccionado en temporal OOF) | **0,5165** | 0,3628 | 0,8961 | 0,9279 | 0,5110 | 0,65327 |

XGBoost se selecciono por F1 temporal OOF de entrenamiento 0,4316, no por el
test. Aunque RF tuvo mayor F1 de holdout, seleccionarlo con esa informacion
habria contaminado la evaluacion. XGBoost matriz de confusion, filas reales
`[0,1]`, columnas predichas `[0,1]`: `[[6828,1196],[79,681]]`. El baseline
positivo del holdout es 760/8.784 = 8,65 %; PR-AUC se reporta por el
desbalance, no accuracy como metrica principal.

La clasificacion publica comprobada para la fila real `r013_c007`,
`2026-10-10`, devolvio probabilidad `0.0714572966`, threshold `0.6532685161`,
clase `false`.

## 5. Operacion, despliegue y recuperacion

- **Hosting:** Render, plan Free, Docker, auto-deploy desde `main`. Puede
  suspenderse/hibernar por inactividad y el cold start es variable; no existe
  SLA garantizado por este proyecto.
- **CD:** `.github/workflows/cd.yml` lee Actions variable `APP_URL` y espera
  `/health`, `/model-info`, `/predict`: connect timeout 15 s, read timeout
  75 s, hasta 12 intentos con 10 s entre intentos.
- **CI:** checkout, Python 3.11, requirements fijos, Ruff, pytest con cobertura,
  `docker compose config` y build Docker.
- **Data update:** semanal (cron lunes 06:17 UTC) o manual. End date se elige
  siete dias atras para Archive. `MAP_KEY` debe existir como GitHub Actions
  secret; workflow imprime solo configurada sí/no. Upload de artifact
  procesado/reportes por 14 dias, sin `data/raw`.
- **Retrain:** obtiene el artifact de la ejecucion data update, corre Optuna y
  compara F1 de validacion temporal OOF del candidato con el metadata del
  modelo actual; solo promociona/pushea si mejora estrictamente. En manual,
  se indica `data_run_id` de una descarga que termino correctamente.
- **Monitoring:** calcula PSI por feature comparando ultimos 30 dias con 90
  previos, y cambio absoluto de tasa positiva. `PSI >= 0.20` es bandera para
  revision; artifact con retencion 30 dias.
- **Rollback:** revertir el commit de promocion/actualizacion en Git sin
  reescribir historia; Render vuelve a desplegar `main`. Confirmar luego
  `/health` y `/model-info`. No desplegar un modelo no revisado manualmente.

### Ejecucion observada de automatizaciones (17-oct-2026)

- [Data update, run 39074137185](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39074137185):
  job de descarga exitoso; rango solicitado `2024-10-10`–`2026-10-10`,
  43.344 filas integradas de `2024-11-11` a `2026-10-10`, 2.218 positivas,
  41.126 negativas y 7.206 detecciones retenidas. El artifact procesado se
  subio correctamente; no contiene CSV FIRMS/Open-Meteo crudos.
- [Retrain, run 39075036568](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39075036568):
  se entrenaron cuatro candidatos, con 10 trials Optuna cada uno. El mejor
  candidato por validacion temporal fue HistGradientBoosting con F1 `0.425635`,
  frente al vigente `0.431636`. No hubo promocion. Por tanto, el modelo en
  `main` y Render sigue siendo el XGBoost previamente evaluado y sus metricas
  de produccion en la seccion 4 no se reemplazaron por las del candidato.
  El candidato tuvo F1 `0.5090`, precision `0.3552`, recall `0.8974`,
  ROC-AUC `0.9262`, PR-AUC `0.4806` y threshold `0.62653` en holdout; estos
  valores son informativos y no constituyen el modelo desplegado.
- [Monitoring, run 39075038467](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39075038467):
  job exitoso; referencia `2026-06-13`–`2026-09-10` (9.072 filas) y ventana
  reciente `2026-09-11`–`2026-10-10` (4.032 filas). Cambio absoluto de tasa
  positiva `0.038057`; 9 features superaron PSI `0.20`. Requiere revision
  operativa de distribuciones, etiquetas y calidad de fuente; el umbral de
  PSI es alerta de monitoreo, no diagnostico automatico de degradacion.

## 6. Seguridad y datos sensibles

- `.env`, `MAP_KEY`, respuestas crudas FIRMS/Open-Meteo, y dataset procesado
  local estan excluidos de Git y Docker context/runtime.
- `MAP_KEY` solo se define como GitHub Actions secret para el workflow de
  ingesta; no se necesita en Render.
- El modelo y metadata finales se versionan deliberadamente como artefactos
  pequenos para que builds sean reproducibles. CSV procesado temporal para
  retraining/drift se transfiere como Actions artifact de retencion limitada.
- La UI y la API son publicas; evitar enviar datos personales o sensibles.
- Rotar cualquier clave previamente compartida fuera del gestor de secretos.

## 7. Evidencias y estado de automatizaciones

- Prueba externa observada: GET `/health`, GET `/model-info`, POST `/predict`
  en URL publica; respuestas en `reports/render_public_smoke.json`.
- Workflow CD nuevo despues de commit `289e971`: corrida
  `39074089022`, job `smoke-test-render` success. Tras soporte manual
  agregado, corrida `39074115212` tambien paso el smoke test. Los enlaces se
  encuentran en [GitHub Actions](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions).
- Los resultados reales del ciclo de datos, retraining y drift del 17-oct-2026
  estan documentados en la seccion 5 y en [fase 5](./fase_5.md). La corrida
  de reentrenamiento no supero el criterio temporal, de modo que no genero
  despliegue ni cambio las metricas actuales del modelo.

Fuentes versionadas de verdad: `reports/real_metrics.json`,
`docs/fase_1.md`, `docs/fase_2.md`, `docs/fase_4.md` y logs/runs de Actions.
