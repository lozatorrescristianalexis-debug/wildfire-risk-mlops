# Fase 2: entrenamiento y evaluacion

## Registro historico de desarrollo (no usar en el informe final)

El pipeline entrena un clasificador Random Forest reproducible y evalua en un
bloque cronologico de fechas posteriores (80/20), guardando metricas de
clasificacion. La etiqueta representa una deteccion FIRMS del mismo dia y las
variables incluyen el tiempo de ese dia; esto es retrospectivo, no un nowcast,
pronostico de incendios futuros ni estimacion de riesgo causal.

En la implementacion inicial `data-demo` genero datos sinteticos deterministas
para probar el software. Los numeros guardados abajo son exclusivamente
evidencia de prueba del codigo; **no son resultados del trabajo final, no son
datos reales y deben excluirse del informe y exposicion**. La version actual
aisla esas salidas en `data/demo/`, `models/demo/` y `reports/demo/`, y bloquea
su uso en entrenamiento final.

## Archivos principales

- `src/wildfire/demo.py`: conjunto sintetico para demostracion.
- `src/wildfire/model.py`: validacion, particion cronologica, ajuste y scoring.
- `tests/test_model.py`: pruebas de reproducibilidad y ciclo de entrenamiento.
- Salidas iniciales movidas a directorios demo: `data/demo/daily.csv`,
  `models/demo/wildfire.joblib` y `reports/demo/metrics.json` (ignoradas por Git).

## Resultados y evidencia

- `.\scripts\run.ps1 data-demo` -> 1,095 filas sinteticas, 41 positivas, semilla
  42; datos locales en `data/processed/daily.csv` (ignorado por Git).
- `.\scripts\run.ps1 train` -> particion temporal de 876 filas de entrenamiento
  y 219 de prueba; el intervalo de prueba fue `2025-05-27` a `2025-12-31`.
- Metricas del holdout sintetico: accuracy `0.9224`, precision `0.3077`,
  recall `0.3333`, F1 `0.3200`, ROC-AUC `0.8035`; matriz de confusion
  `[[198, 9], [8, 4]]`. El bajo recall/precision y el origen sintetico impiden
  interpretar esto como resultado de deteccion de incendios reales.
- El resultado del ejemplo mas reciente fue una probabilidad `0.0000`,
  prediccion `0`, etiqueta sintetica observada `0`, fecha `2025-12-31`.
- Evidencias sinteticas locales ignoradas: `models/demo/wildfire.joblib` y
  `reports/demo/metrics.json`.
- No se generaron figuras ni logs de ejecucion; las metricas del experimento
  estan en el JSON indicado, que se excluye de Git junto al modelo.
- `.\.venv\Scripts\python.exe -m pytest -q` -> 11 pruebas pasaron sin warnings.
