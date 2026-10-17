# Fase 1: ingesta y preparacion de datos reales

## Region, fuentes y periodo

- Region: departamento amazonico de Madre de Dios, Peru. Se eligio una sola
  unidad administrativa para no mezclar jurisdicciones ni climas.
- Bounding box FIRMS (`oeste,sur,este,norte`):
  `-72.4287387,-13.3413977,-68.6519906,-9.9069082`, derivado de la frontera
  administrativa de OpenStreetMap (relacion
  [1891287](https://www.openstreetmap.org/relation/1891287)).
- Malla de 0.25 grados: 144 celdas que intersectan el departamento. Los puntos
  meteorologicos representan el centro de cada celda.
- Periodo solicitado a ambas fuentes: `2024-10-10` a `2026-10-10`, inclusive.
- Solo se usaron respuestas reales de NASA FIRMS y Open-Meteo. No se incorporo
  el conjunto sintetico `data/demo/`.

## Resultado de descargas

NASA FIRMS VIIRS SNPP standard (`VIIRS_SNPP_SP`) devolvio 11.845 detecciones,
con fechas observadas entre `2024-10-10` y `2026-06-30`. El complemento
near-real-time (`VIIRS_SNPP_NRT`) se solicito para la ventana movil maxima
disponible, `2026-08-19` a `2026-10-10`, y devolvio 5.171 detecciones entre
`2026-08-21` y `2026-10-10`. Total bruto: **17.016 detecciones**. El historico
se descargo en 147 ventanas de cinco dias y NRT en 11 ventanas; los bloques estan
guardados individualmente en `data/raw/` para reanudar sin repetir llamadas.

Los rangos anteriores son las fechas de las detecciones recibidas, no una
garantia de observacion diaria. FIRMS no devolvio detecciones SP despues del
30-jun y el primer registro NRT es 21-ago; queda una brecha de fechas
`2026-07-01` a `2026-08-20`. Esa brecha no se interpreto como ausencia de
incendios ni se relleno. Las respuestas para el bounding box incluyeron
detecciones fuera del poligono o sin celda valida: 9.523 se excluyeron y 7.493
quedaron asignadas a celdas del area antes del calentamiento de rezagos.

Open-Meteo Archive devolvio datos diarios reales para las 144 celdas y los 731
dias del periodo: **105.264 filas**, sin nulos meteorologicos. Hubo una
respuesta HTTP 429 durante la primera descarga de la malla. Se reanudo desde
los bloques cacheados con espera/reintentos, y la descarga final termino sin
rellenos. Cache por bloque: `data/raw/open_meteo_grid_*.csv`; salida consolidada:
`data/raw/open_meteo_daily.csv`.

## Dataset celda-dia

La integracion genero `data/processed/real_daily.csv` (ignorado por Git):

| Resultado | Valor |
| --- | ---: |
| Filas tras filtros de actividad y calentamiento | 37.584 |
| Fechas activas conservadas | 261 (`2024-11-11` a `2026-10-10`) |
| Celdas | 144 |
| Etiqueta 1 (celda con deteccion) | 1.964 |
| Etiqueta 0 (sin deteccion local en fecha con actividad regional) | 35.620 |
| Tasa positiva | 5,23 % |
| Detecciones en las filas conservadas | 6.637 |
| Nulos en las variables de entrada tras filtros | 0 |

La etiqueta positiva representa una deteccion FIRMS en la celda y dia. Los
negativos se limitan a fechas con al menos una deteccion en alguna celda del
departamento; no confirman ausencia de fuego ni sobrevuelo satelital local. Se
descartaron 2.880 filas activas por calentamiento de lags/ventanas o falta de
features previas. Las variables de entrada contienen meteorologia rezagada,
medias moviles y acumulados de precipitacion; no usan el clima del dia objetivo.

## Evidencias y comando

- Ejecucion completada: `.\scripts\run.ps1 data` (exit code 0).
- Resumen reproducible de fuentes, nulos y filtros:
  `reports/real_ingestion.json`.
- Cobertura por fuente: `data/raw/firms_source_coverage.json` (ignorado por Git).
- Descargas FIRMS por bloques, geometria y clima original: `data/raw/` (ignorado).
- Dataset integrado: `data/processed/real_daily.csv` (ignorado).
- Las llamadas no imprimen ni guardan `MAP_KEY` en los reportes.
