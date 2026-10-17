# Fase 4: datos reales de Madre de Dios

## Region y configuracion

- Departamento elegido: Madre de Dios, Peru.
- FIRMS bounding box (`oeste,sur,este,norte`):
  `-72.4287387,-13.3413977,-68.6519906,-9.9069082`.
- Punto Open-Meteo representativo: latitud `-12.0`, longitud `-70.25`.
- El rectangulo procede del bounding box de la relacion administrativa de
  OpenStreetMap [1891287](https://www.openstreetmap.org/relation/1891287).
  Open-Meteo consulta el punto indicado; no un promedio del departamento.
- Fuente historica: NASA FIRMS `VIIRS_SNPP_SP`.
- Periodo predeterminado: 2024-10-10 a 2026-10-10 (731 fechas inclusivas;
  dos años completos, con siete dias de margen para datos meteorologicos
  recientes). Se puede configurar `START_DATE`/`END_DATE` en `.env`, pero el
  pipeline final exige al menos un año.

Se escogio un solo departamento amazonico para mantener una unidad geografica
definida sin mezclar jurisdicciones o climas. La caja es una aproximacion
rectangular de la frontera administrativa, requisito de la consulta FIRMS, por
lo que puede incluir una franja fuera de la frontera.

## Descargas y limites

FIRMS se consulta secuencialmente en ventanas de hasta cinco dias con el
endpoint historico
`/api/area/csv/{MAP_KEY}/{SOURCE}/{BBOX}/{DAY_RANGE}/{DATE}`. Para 731 dias son
147 solicitudes maximas. La pagina oficial de la [FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/)
describe la necesidad de `MAP_KEY` y su limite de transacciones. Open-Meteo se
consulta en bloques de hasta 30 dias.
Las respuestas originales se guardan en `data/raw/`, y la tabla diaria real en
`data/processed/real_daily.csv`. No se rellenan fallos ni dias sin respuesta
con datos sinteticos.

## Aislamiento de los datos sinteticos

`data-demo` escribe unicamente en `data/demo/daily.csv`. El antiguo CSV, modelo
y JSON sintéticos usados durante la configuracion se movieron a `data/demo/`,
`models/demo/` y `reports/demo/`. Estan ignorados por Git. El entrenamiento CLI
usa por defecto el CSV real, exige `data_source=firms_open_meteo` y rechaza
`synthetic_demo`. El modelo/metricas finales son
`models/wildfire_real.joblib` y `reports/real_metrics.json`.

## Resultado de la ejecucion real en este entorno

Open-Meteo si respondio con 731 filas diarias reales, desde 2024-10-10 hasta
2026-10-10, sin valores faltantes. La respuesta se conserva en
`data/raw/open_meteo_daily.csv`, ignorada por Git. No se integro en un dataset
final porque falta FIRMS. No se pudieron iniciar solicitudes HTTP FIRMS ni
entrenar con datos reales: al comprobar el workspace no existia
`E:\aprendizaje de maquina\.env`, y el proceso tampoco tenia una variable
`MAP_KEY`. El comando de ingesta se detuvo antes de hacer una solicitud FIRMS
con el mensaje `MAP_KEY is missing`; por tanto:

- observaciones meteorologicas reales descargadas: **731 filas**;
- detecciones FIRMS reales descargadas: **ninguna** (API no llamada);
- filas integradas reales para entrenamiento: **ninguna**;
- periodo configurado: **2024-10-10 a 2026-10-10**;
- balance de clases real: **no disponible sin detecciones FIRMS**;
- metricas de entrenamiento real: **no generadas**.

No se reportan metricas sinteticas como resultados del informe. Para reanudar,
verifica que tu clave este en `E:\aprendizaje de maquina\.env` (no en
`.env.example`, y sin compartirla en el chat) y ejecuta
`.\scripts\run.ps1 data`, `.\scripts\run.ps1 train` y
`.\scripts\run.ps1 test`. Si FIRMS responde con un error, la ingesta falla sin
crear dataset real y su mensaje queda en la terminal.

## Validacion del codigo

- `.\.venv\Scripts\python.exe -m pytest -q` -> 15 pruebas aprobadas.
- `.\.venv\Scripts\python.exe -m pip check` -> sin dependencias rotas.
- `docker build -t wildfire-firms .` -> imagen construida correctamente.
- `docker run --rm wildfire-firms data-demo --days 30` -> la salida quedo en
  `data/demo/` dentro del contenedor, aislada del dataset real.
- `python -m src.wildfire.cli train --input data/demo/daily.csv` -> fallo
  intencional con `Synthetic demo data cannot be used for final training or
  report metrics.`
