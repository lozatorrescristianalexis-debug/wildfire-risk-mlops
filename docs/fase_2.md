# Fase 2: entrenamiento y evaluacion con datos reales

## Protocolo

El entrenamiento final se hizo exclusivamente con
`data_source=firms_open_meteo` desde `data/processed/real_daily.csv`; el cargador
rechaza `synthetic_demo`. Se compararon regresion logistica (baseline), Random
Forest, HistGradientBoosting y XGBoost. Optuna TPE hizo 10 pruebas por modelo,
optimizando average precision sobre tres folds temporales expansivos.

La evaluacion final separa por fecha: 80 % de las fechas activas mas antiguas
para entrenamiento y 20 % mas recientes para prueba. No hay fecha compartida
entre particiones. El umbral de cada modelo se eligio para maximizar F1 en
predicciones out-of-fold del entrenamiento; el holdout no se uso en ajuste ni
seleccion. Por el desbalance, se reportan PR-AUC, precision, recall y F1; no se
usa accuracy como metrica principal.

La tarea es clasificacion retrospectiva de celda-dia, no pronostico futuro ni
estimacion causal. La etiqueta negativa significa que no hubo deteccion en esa
celda durante una fecha con alguna deteccion regional; no verifica ausencia de
fuego ni cobertura satelital en cada celda.

## Datos de la evaluacion

- Fuente: FIRMS + Open-Meteo reales, sin datos demo.
- Filas: 37.584 (1.964 positivas y 35.620 negativas; tasa positiva 5,23 %).
- Fechas activas: 261; dataset `2024-11-11` a `2026-10-10`.
- Entrenamiento: 29.952 filas, 1.309 positivas.
- Holdout temporal: 7.632 filas (`2026-06-06` a `2026-10-10`), 655 positivas
  y 6.977 negativas.
- Optuna: 10 trials por modelo, tres folds temporales.

## Metricas en el holdout temporal

| Modelo | F1 | Precision | Recall | ROC-AUC | PR-AUC |
| --- | ---: | ---: | ---: | ---: | ---: |
| Logistic (baseline) | 0,3413 | 0,2342 | 0,6290 | 0,8183 | 0,2019 |
| Random Forest | 0,5214 | 0,3803 | 0,8290 | 0,9291 | 0,4992 |
| HistGradientBoosting | 0,5771 | 0,4336 | 0,8626 | 0,9390 | 0,5347 |
| XGBoost (seleccionado por validacion temporal) | 0,5506 | 0,4014 | 0,8763 | 0,9335 | 0,5252 |

Modelo final guardado: XGBoost. La seleccion se baso unicamente en F1
out-of-fold del entrenamiento (0,4747; desempate por PR-AUC de CV), no en el
holdout. Aunque HistGradientBoosting obtuvo mejores cifras observadas en este
holdout, no se cambio la seleccion usando el test. Umbral final de XGBoost:
**0,71171**, obtenido de predicciones temporales out-of-fold.

Matriz de confusion de XGBoost, filas = clase real `[0, 1]`, columnas =
prediccion `[0, 1]`:

```text
[[6121, 856],
 [  81, 574]]
```

El holdout de XGBoost obtuvo F1 `0,5506`, precision `0,4014`, recall `0,8763`,
ROC-AUC `0,9335` y PR-AUC `0,5252`.

## Artefactos y reproducibilidad

- Modelo real: `models/wildfire_real.joblib` (local, ignorado por Git).
- Metricas detalladas y parametros: `reports/real_metrics.json` (local).
- Resumen de ingesta: `reports/real_ingestion.json`.
- Figuras: `reports/figures/eda_real.png`,
  `model_comparison_real.png`, `roc_pr_real.png`,
  `confusion_matrix_real.png` y `feature_importance_real.png`.
- Entrenamiento observado:
  `.\.venv\Scripts\python.exe -m src.wildfire.cli train --trials 10`
  (exit code 0; cuatro modelos completados).
- Validacion automatizada: `.\.venv\Scripts\python.exe -m pytest -q`
  (19 pruebas aprobadas).
- Dependencias: `.\.venv\Scripts\python.exe -m pip check`
  (sin dependencias rotas).

Los resultados dependen de la cobertura FIRMS recuperada. En particular, las
detecciones SP observadas terminan el `2026-06-30` y las detecciones NRT
comienzan el `2026-08-21`; el intervalo intermedio no se completa con etiquetas
sinteticas ni se considera ausencia de incendios.
