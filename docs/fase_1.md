# Fase 1: ingesta y preparacion de datos reales

## Region, fuentes y periodo

- Region: departamento amazonico de Madre de Dios, Peru, acotado a una unidad
  administrativa para no mezclar jurisdicciones ni climas.
- Bounding box FIRMS (`oeste,sur,este,norte`):
  `-72.4287387,-13.3413977,-68.6519906,-9.9069082`, derivado del bounding box
  de la relacion administrativa de
  [OpenStreetMap 1891287](https://www.openstreetmap.org/relation/1891287).
- Malla meteorologica de 0.25 grados, recortada por interseccion con el
  poligono: 144 celdas.
- Periodo de FIRMS/Open-Meteo: `2024-10-10` a `2026-10-10`, inclusive.
- No se uso `data/demo/` en la integracion ni el modelo final.

## Descargas y cobertura por producto

FIRMS SNPP estandar (`VIIRS_SNPP_SP`) devolvio 11.845 detecciones brutas
(`2024-10-10` a `2026-06-30`); 5.123 detecciones quedaron dentro del
departamento en 235 fechas. El complemento SNPP NRT se pidio desde
`2026-08-19` hasta `2026-10-10`: 5.171 detecciones brutas, 2.370 dentro de la
frontera en 46 fechas (`2026-08-21` a `2026-10-10`).

Se consultaron cinco productos alternativos exclusivamente para la brecha
`2026-07-01`–`2026-08-20` (51 dias). Los resultados son por producto, no se
presentan como una unica fuente homogenea:

| Producto FIRMS | Detecciones en bbox | Dentro del poligono | Fechas activas dentro | Rango dentro del poligono |
| --- | ---: | ---: | ---: | --- |
| `VIIRS_NOAA20_SP` | 0 | 0 | 0 | Sin detecciones |
| `VIIRS_NOAA20_NRT` | 600 | 288 | 32 | 2026-07-03–2026-08-17 |
| `VIIRS_NOAA21_NRT` | 552 | 246 | 35 | 2026-07-01–2026-08-20 |
| `MODIS_SP` | 36 | 18 | 12 | 2026-07-02–2026-07-31 |
| `MODIS_NRT` | 37 | 17 | 5 | 2026-08-06–2026-08-15 |

En conjunto hubo al menos una deteccion dentro del poligono en 40 de los 51
dias; en 11 dias no se recibio deteccion de estos productos. Esto no acredita
cobertura satelital ni ausencia de incendio en esos dias. Los productos NOAA20,
NOAA21 y MODIS se combinaron para etiquetas de actividad, pero cada deteccion
conserva sus nombres de producto en la columna `firms_sources`; la comparacion
temporal del modelo evalua esta definicion multifuente. Los productos crudos y
sus respuestas por bloque permanecen en `data/raw/`, ignorados por Git.

Total para las fuentes solicitadas en el periodo: **18.241 detecciones brutas
en el bbox**, de las cuales 8.062 caen dentro del poligono antes de deduplicar
observaciones coincidentes. Se excluyeron 10.179 por estar fuera del poligono
o de la malla. La deduplicacion de coordenada, fecha, satelite e instrumento
mantiene una atribucion conjunta de los productos coincidentes.

Open-Meteo Archive devolvio **105.264 filas** (144 celdas x 731 dias) sin
nulos meteorologicos. Una respuesta inicial fue HTTP 429; con cache por bloque,
pausas y reintentos se completo sin datos de relleno. `reports/real_ingestion.json`
registra el balance y filtros; `reports/firms_gap_alternative_sources.json`
guarda los resultados por sensor de la busqueda acotada.

## Dataset integrado

`data/processed/real_daily.csv` contiene ejemplos celda-dia solo de fechas con
actividad FIRMS regional, despues del calentamiento de rezagos:

| Resultado | Valor |
| --- | ---: |
| Filas | 43.344 |
| Fechas con filas | 301 (`2024-11-11`–`2026-10-10`) |
| Celdas | 144 |
| Positivas | 2.218 (5,12 %) |
| Negativas | 41.126 |
| Detecciones conservadas | 7.206 |
| Nulos en CSV integrado | 0 |

Clase 1 significa deteccion FIRMS en la celda y fecha. Clase 0 significa sin
deteccion local en una fecha con alguna deteccion en el departamento; sigue
siendo un proxy de observacion, no ausencia verificada. Las features usan clima
rezagado, medias moviles y acumulados de precipitacion, no el clima del mismo
dia objetivo. Se retiraron 2.880 filas por calentamiento o clima incompleto.

## Evidencia

- `.\scripts\run.ps1 data` -> exit code 0; bloques FIRMS ya descargados y cache
  meteorologica reutilizada.
- Dataset: `data/processed/real_daily.csv` (local e ignorado por Git).
- Clima y respuestas/bloques FIRMS: `data/raw/` (local e ignorado por Git).
- Cobertura y filtros: `reports/real_ingestion.json`.
- Intento de cubrir la brecha por producto: `reports/firms_gap_alternative_sources.json`.
- `MAP_KEY` se lee desde `.env`; no se imprime ni se incluye en artefactos.
