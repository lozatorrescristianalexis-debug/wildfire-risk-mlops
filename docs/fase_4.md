# Fase 4: datos reales de Madre de Dios

## Region y configuracion

- Departamento amazonico: Madre de Dios, Peru.
- Bounding box FIRMS (`oeste,sur,este,norte`):
  `-72.4287387,-13.3413977,-68.6519906,-9.9069082`, derivado del bounding box
  de la relacion administrativa
  [OpenStreetMap 1891287](https://www.openstreetmap.org/relation/1891287).
- Periodo solicitado: `2024-10-10` a `2026-10-10`, inclusivo.
- Malla: 144 celdas de 0.25 grados que intersectan el poligono.
- Se uso exclusivamente `VIIRS_SNPP_SP`, `VIIRS_SNPP_NRT` y Open-Meteo
  Archive; ninguna salida de `data-demo` se uso en el entrenamiento final.

Madre de Dios se escogio para acotar el problema a una unidad administrativa
amazonica sin mezclar departamentos. FIRMS consulta un rectangulo; los puntos
se filtraron posteriormente contra la geometria administrativa y se asignaron
a una malla espacial.

## Descargas reales y cobertura

FIRMS devolvio 11.845 detecciones SP (`2024-10-10` a `2026-06-30`) y 5.171
detecciones NRT (`2026-08-21` a `2026-10-10`), 17.016 brutas en total. NRT se
solicito para los 60 dias moviles disponibles, desde `2026-08-19`. Los
rangos expresan las primeras y ultimas fechas con detecciones devueltas, no
garantizan cobertura en cada fecha. Se observa una brecha entre el 1 de julio
y el 20 de agosto de 2026. No se inventaron detecciones, negativos ni datos de
reemplazo para ese intervalo.

Open-Meteo devolvio 105.264 filas celda-dia para 144 celdas y 731 dias, sin
nulos meteorologicos. Se recibio HTTP 429 en una ejecucion inicial de la API;
se agregaron pausas conservadoras y cache por bloque, y la ejecucion reanudada
completo los datos reales. No hubo error final de FIRMS.

La integracion resulto en 37.584 ejemplos celda-dia para fechas activas entre
`2024-11-11` y `2026-10-10`, con 1.964 positivos (5,23 %), 35.620 negativos y
cero nulos en las features finales. Los negativos solo se forman en fechas
con detecciones en alguna celda del departamento y son un proxy de actividad
del satelite, no ausencia confirmada de fuego. 6.637 detecciones permanecen
en las filas integradas tras el calentamiento de variables rezagadas.

El detalle de filas, filtros y balance esta en
[`real_ingestion.json`](../reports/real_ingestion.json); la cobertura por
fuente esta en `data/raw/firms_source_coverage.json` (local, ignorado por Git).
Los datos raw y el dataset procesado tambien se mantienen locales e ignorados.
`MAP_KEY` se lee desde `.env`; su valor no se escribe en codigo, reportes ni
Git.

## Modelo real

Optuna ajusto cuatro clasificadores durante 10 trials por modelo con tres
folds temporales. La particion de prueba contiene 7.632 filas entre
`2026-06-06` y `2026-10-10`, separada por fechas. XGBoost se selecciono usando
predicciones out-of-fold de entrenamiento, con umbral `0.71171`. En el holdout
obtuvo F1 `0.5506`, precision `0.4014`, recall `0.8763`, ROC-AUC `0.9335` y
PR-AUC `0.5252`; confusion matrix `[[6121, 856], [81, 574]]`.
HistGradientBoosting obtuvo mayores metricas observadas en el holdout, pero no
se uso ese conjunto para elegir el modelo. Esta tarea es una clasificacion
retrospectiva, no un pronostico operacional.

Las tablas completas estan en [`fase_2.md`](fase_2.md) y las figuras en
`reports/figures/`. El modelo `models/wildfire_real.joblib` y
`reports/real_metrics.json` se generan localmente y se excluyen de Git.

## Validacion ejecutada

- `.\scripts\run.ps1 data` -> ingesta real integrada, exit code 0.
- `.\.venv\Scripts\python.exe -m src.wildfire.cli train --trials 10` ->
  cuatro modelos entrenados y comparados, exit code 0.
- `.\.venv\Scripts\python.exe -m pytest -q` -> 19 pruebas aprobadas.
- `.\.venv\Scripts\python.exe -m pip check` -> sin dependencias rotas.
- `git check-ignore -v .env` -> `.env` ignorado por Git.
