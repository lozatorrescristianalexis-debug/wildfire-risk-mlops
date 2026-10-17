# Fase 1: ingesta y preparacion de datos

## Alcance

Se implemento una ingesta configurable de detecciones FIRMS y meteorologia
historica diaria de Open-Meteo. La salida es una fila por dia con cuatro
variables meteorologicas, las coordenadas configuradas, la cantidad de
detecciones FIRMS y una etiqueta binaria de deteccion observada ese dia.

La coordenada meteorologica predeterminada es Madrid y el area FIRMS
predeterminada es la peninsula iberica (`-5,36,4,44`); ambos se pueden cambiar
en `.env`. Open-Meteo consulta un unico punto representativo, no una malla
meteorologica de toda el area. El endpoint de FIRMS por area limita las
descargas a los diez dias mas recientes. FIRMS exige una clave personal en
`MAP_KEY`; para un periodo historico, se admite un CSV FIRMS local.

## Archivos principales

- `src/wildfire/config.py`: configuracion desde `.env` y valores por defecto.
- `src/wildfire/ingest.py`: clientes HTTP, normalizacion FIRMS y union diaria.
- `src/wildfire/cli.py`: comandos `data` y `data-demo`.
- `tests/test_ingest.py`: pruebas de normalizacion, validacion y APIs simuladas.

## Resultados y evidencia

- Open-Meteo se consulto en vivo para Madrid (`40.4168, -3.7038`) y el periodo
  `2026-10-08` a `2026-10-17`; respondio 10 filas diarias con las cuatro
  variables esperadas.
- `.\scripts\run.ps1 data` intento la ingesta FIRMS y termino explicitamente
  con `MAP_KEY is missing`; no se descargo ni se simulo ningun dato FIRMS real.
- `.env` no existia en el workspace y no se incluyo ninguna clave.
- Los tests de ingesta validan CSV, agrupacion diaria, union y manejo de errores.
- Para completar la descarga FIRMS en vivo, agrega una clave personal a `.env`
  y ejecuta `.\scripts\run.ps1 data`.
