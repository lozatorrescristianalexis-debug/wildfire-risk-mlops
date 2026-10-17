# Fase 9: auditoria contra rubrica del proyecto

## Base de evaluacion y alcance

No se adjunto una rubrica institucional con descriptores, pesos o escala de
calificacion. Para no inventar una nota, esta matriz es una **auditoria
provisional** derivada de los entregables y requisitos especificados en esta
conversacion. Los estados indican evidencia revisada, no puntaje academico:

- **Cumple:** evidencia ejecutada o artefacto verificable cubre el criterio.
- **Parcial:** hay resultado/evidencia con una limitacion explicitada.
- **Pendiente:** aun requiere una accion o corrida externa verificable.

Si la asignatura tiene una rubrica oficial, mapear sus criterios/pesos a las
filas de esta matriz antes de asignar una calificacion.

## Matriz de auditoria

| # | Criterio auditado | Estado | Evidencia verificable | Observacion/limitacion |
|---:|---|---|---|---|
| 1 | Problema, region y bounding box reproducibles | Cumple | `docs/fase_1.md`; `src/wildfire/config.py` | Region definida como Madre de Dios; bounding box rectangular recortado por poligono |
| 2 | Fuentes reales trazables y separacion de demo | Cumple | `docs/fase_1.md`; `tests/test_ingest.py`; `data_source` en `reports/real_metrics.json` | No atribuir negativos a ausencia confirmada de fuego |
| 3 | Brecha temporal de fuente analizada | Cumple con limitacion | `reports/firms_gap_alternative_sources.json`; `docs/fase_1.md` | Cobertura alternativa con sensores distintos; 11/51 dias no tuvieron detecciones devueltas |
| 4 | Features temporales y control de leakage | Cumple | `reports/real_metrics.json` (`temporal_split`, tuning); `docs/fase_2.md`; `tests/test_model.py` | Evaluacion retrospectiva; no forecasting |
| 5 | Comparacion, tuning y metricas desbalanceadas | Cumple | `reports/real_metrics.json`; `docs/fase_2.md`; figuras en `reports/figures/` | XGBoost seleccionado con F1 OOF temporal; test reportado aparte |
| 6 | API validada, UI operativa y documentacion HTTP | Cumple | `src/wildfire/api.py`; `tests/test_api.py`; `reports/api_http_evidence.json`; `docs/fase_3.md` | UI completamente en ingles y tabla en lugar de mapa |
| 7 | Contenedor seguro y reproducible | Cumple | `Dockerfile`; `docker-compose.yml`; `reports/docker_http_evidence.json`; `docs/fase_4.md` | Modelo/metadata versionados; `.env`, raw y dataset no estan en imagen |
| 8 | Despliegue externo y prueba de disponibilidad | Cumple | [Render publico](https://wildfire-risk-mlops.onrender.com); `reports/render_public_smoke.json`; runs CD citados en `docs/fase_8_informe_tecnico_ti.md` | Render Free puede dormir y no ofrece SLA |
| 9 | Ingesta automatizada FIRMS/Open-Meteo | Cumple con limitacion de observacion satelital | `.github/workflows/data_update.yml`; [run 39074137185](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39074137185); artifact `real-data-update` | Job exitoso: 43.344 filas integradas, `2024-11-11`–`2026-10-10`, 2.218 positivas, 41.126 negativas y 7.206 detecciones; 11/51 dias de la brecha no tuvieron detecciones devueltas |
| 10 | Promocion de modelo solo ante mejora temporal | Cumple; candidato rechazado correctamente | `.github/workflows/retrain.yml`; [run 39075036568](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39075036568); `reports/real_metrics.json` | Candidato HGB F1 temporal 0,425635 vs vigente 0,431636; no promovido; modelo desplegado permanece XGBoost |
| 11 | Monitoreo de drift con ventana y umbral | Cumple con senales para revision | `src/wildfire/monitor.py`; `.github/workflows/monitoring.yml`; [run 39075038467](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39075038467); artifact `real-data-drift-report` | Ventanas 90/30 dias; cambio absoluto de tasa positiva 0,038057; 9 features PSI >= 0,20; indicador no equivale a fallo |
| 12 | Pruebas, lint, cobertura y build reproducibles | Cumple | `docs/fase_6.md`; CI runs exitosos | 27 pruebas locales; cobertura total registrada 61 % |
| 13 | Proteccion de credenciales/datos | Cumple | `.gitignore`; `.dockerignore`; verificacion `git check-ignore`/`git ls-files` en `docs/fase_4.md` | Rotar clave si fue expuesta fuera de Actions |
| 14 | Documentacion tecnica y exposicion | Cumple | `docs/fase_7_guion_presentacion.md`; `docs/fase_8_informe_tecnico_ti.md`; fases 1–6 | Guion de 14 min y 15 preguntas; informe orientado a TI |

## Datos cuantitativos auditables del modelo actual

- Dataset modelable: 43.344 filas; 2.218 positivas (5,1172 %), 41.126
  negativas; 144 celdas; cero nulos despues del filtrado.
- Holdout: 8.784 filas, 760 positivas, fechas 2026-08-02 a 2026-10-10.
- XGBoost elegido sin usar el holdout: F1 temporal OOF 0,4316; en test F1
  0,5165, precision 0,3628, recall 0,8961, ROC-AUC 0,9279, PR-AUC 0,5110,
  umbral 0,65327.
- Matriz de confusion: `[[6828,1196],[79,681]]`, filas reales 0/1.
- Random Forest tuvo F1 test 0,5238; no reemplaza el seleccionado porque la
  seleccion post hoc con test sesgaria la estimacion.

## Cierre de auditoria

Las filas 9–11 se actualizaron con ejecuciones reales de Actions y resultados
observados. El run de ingesta completo concluyo `success`; el estado agregado
tardo en sincronizarse unos 11 minutos despues de finalizar el job/artifact.
No se asigna puntaje porque falta la rubrica institucional.
