# Fase 2: entrenamiento y evaluacion con datos reales

## Protocolo

El entrenamiento utiliza exclusivamente observaciones reales FIRMS/Open-Meteo.
La variable `firms_sources` conserva la atribucion al producto y durante
`2026-07-01`–`2026-08-20` combina VIIRS NOAA20 NRT, NOAA21 NRT y MODIS
estandar/NRT con SNPP. Esta heterogeneidad queda documentada y significa que
la etiqueta es actividad detectada por alguno de esos sensores, no una medida
homogenea de un sensor ni una prediccion de ocurrencia terrestre.

Se compararon regresion logistica (baseline), Random Forest,
HistGradientBoosting y XGBoost. Optuna TPE realizo 10 pruebas por modelo,
optimizando average precision sobre tres folds temporales expansivos. La
particion final separa por fecha: 80 % de fechas activas mas antiguas para train
y 20 % para holdout. El umbral se eligio maximizando F1 en predicciones
out-of-fold del entrenamiento; el holdout no se uso en ajuste ni seleccion.
Por el desbalance, se reportan PR-AUC, precision, recall y F1.

La tarea es clasificacion retrospectiva de celda-dia usando solo meteorologia
rezagada, no un pronostico futuro ni una alerta operativa. Los negativos son un
proxy FIRMS en fechas con actividad regional y no prueban ausencia de fuego.

## Datos

- Fuente real multifuente FIRMS + Open-Meteo; sin datos de demo.
- Filas: 43.344 (2.218 positivas y 41.126 negativas; tasa positiva 5,12 %).
- Rango: `2024-11-11` a `2026-10-10`, 301 fechas y 144 celdas.
- Entrenamiento: 34.560 filas, 1.458 positivas.
- Holdout temporal: 8.784 filas (`2026-08-02` a `2026-10-10`), 760 positivas,
  8.024 negativas.
- Optuna: 10 trials por modelo, tres folds temporales.

## Metricas del holdout

| Modelo | F1 | Precision | Recall | ROC-AUC | PR-AUC |
| --- | ---: | ---: | ---: | ---: | ---: |
| Logistic (baseline) | 0,3485 | 0,2322 | 0,6987 | 0,8149 | 0,2016 |
| Random Forest | 0,5238 | 0,3759 | 0,8632 | 0,9293 | 0,5166 |
| HistGradientBoosting | 0,5090 | 0,3552 | 0,8974 | 0,9262 | 0,4806 |
| XGBoost (seleccionado por validacion temporal) | 0,5165 | 0,3628 | 0,8961 | 0,9279 | 0,5110 |

Se mantiene XGBoost porque tuvo el mayor F1 out-of-fold de entrenamiento
(0,4316); Random Forest tuvo mayor F1 en el holdout (0,5238), pero no se
selecciono usando datos de prueba. Umbral XGBoost: **0,65327**.

Matriz de confusion XGBoost (filas reales `[0, 1]`, columnas predichas
`[0, 1]`):

```text
[[6828, 1196],
 [  79,  681]]
```

## Artefactos y comandos ejecutados

- Modelo: `models/wildfire_real.joblib` (402 KB).
- Metricas: `reports/real_metrics.json`.
- Dataset local: `data/processed/real_daily.csv`; los datos brutos permanecen
  unicamente en `data/raw/`.
- Figuras: `reports/figures/` (EDA, comparacion, curvas ROC/PR, confusion e
  importancia).
- `.\.venv\Scripts\python.exe -m src.wildfire.cli train --trials 10` ->
  exit code 0, cuatro modelos y Optuna completados.
- La ejecucion advirtio que Windows no pudo detectar nucleos fisicos y uso el
  conteo de nucleos logicos; el entrenamiento si termino correctamente.

El resumen numerico completo y los parametros de cada modelo estan en
`reports/real_metrics.json`. La seleccion no se baso en el conjunto holdout.
