# Datos completos para el mapa, conservando la aplicación

## Diagnóstico comprobado

El endpoint anterior `/api/historical-fires` leía exclusivamente
`web/historical_fires.json`: **250 puntos**, 33 etiquetas regionales distintas de
su posición y 12 puntos fuera del límite administrativo peruano. La aplicación
no mostraba los CSV descargados para el entrenamiento. El orden Leaflet
`[latitud, longitud]` ya era correcto; intercambiarlo no solucionaba el problema.

Los siete CSV consolidados existentes en `data/raw/` contienen **204.308
observaciones**, de las cuales **130.414** caen dentro del GeoJSON de Perú.
Son detecciones en coordenadas originales, no centros de celdas del modelo.
El resto cae fuera de ese límite: una consulta rectangular también puede traer
países vecinos. No se traslada ni se inventa una posición para incluirlo.

La actualización real del **21 de octubre de 2026**, usando cuatro sensores NRT
entre el 8 y el 21 de octubre, dejó **227.910 observaciones** y **148.067 dentro
de Perú**. Las cuatro consultas respondieron por Area API. Estas cifras son el
estado de esa descarga, no una garantía de cobertura completa de los satélites.

La comparación con `/home/roger/Documents/Git/MLopsSolar` mostró otra diferencia:
`frontend/src/pages/Map.tsx` consulta radiación/UV en Open-Meteo para el punto
seleccionado y dibuja diez ciudades definidas en `backend/app/services/locations.py`.
Ese proveedor puede devolver una celda meteorológica donde FIRMS no registra
ninguna detección. Ambos usan coordenadas, pero **no representan la misma data**.

## Solución implementada

Se conserva FastAPI, Leaflet, el modelo y las pantallas. Un módulo independiente,
`src/wildfire/observations.py`, genera `web/fire_observations.json.gz` con todos
los registros válidos disponibles. La muestra antigua queda solo para
compatibilidad; el mapa de Observaciones usa la nueva API.

- Se preservan latitud, longitud y hora UTC de adquisición. La identidad incluye
  fecha, hora, coordenadas, satélite e instrumento: dos pasadas del mismo día
  no se fusionan. Duplicados exactos SP/NRT conservan ambas atribuciones y
  priorizan el procesamiento estándar.
- La confianza VIIRS `l/n/h` y MODIS numérica se normaliza a baja/nominal/alta;
  valores desconocidos permanecen desconocidos. FRP inválida se devuelve como
  `null`. No se inventan coordenadas ni se redondean a la malla de entrenamiento.
- La asignación regional usa el GeoJSON local, también en el navegador.
- Los filtros se aplican antes de paginar. `total`, `next_offset` y `snapshot_id`
  permiten verificar que se recibieron todos los resultados. Si cambia el
  archivo durante una consulta, HTTP 409 obliga a recargar una versión coherente.
- El mapa usa canvas, filtros por fecha, instrumento y confianza, contador total
  y contador de la vista, procedencia y última fecha disponible. Por defecto
  consulta siete días calendario hasta la última detección disponible; el
  período es visible y existe la opción de consultar todo el archivo.

### API

```text
GET /api/fire-observations/status
GET /api/fire-observations?region=peru&start_date=2026-10-01&end_date=2026-10-21&limit=2000&offset=0
```

Parámetros: `region=peru|all|id_regional`, `confidence=all|nominal|high|low|unknown`,
`instrument=all|VIIRS|MODIS`, fechas ISO, `bbox=oeste,sur,este,norte`,
`limit` de 1 a 5000, `offset` no negativo. `nominal` incluye alta.
`region=all` permite inspeccionar también registros fuera de Perú.
En páginas sucesivas se envía el `snapshot_id` de la primera.

Los metadatos informan origen, fechas, registros por producto, calidad,
antigüedad, uso de respaldo y resultado del último intento de descarga.
Los conteos por fuente pueden solaparse si una observación pertenece a SP y NRT.

## Descarga y respaldo

La cadena es **Area API → CSV oficial de cada sensor → último archivo válido**.

1. Con `MAP_KEY`, se consulta `data_availability` y se selecciona la última
   fecha publicada de cada producto, sin asumir que todos llegan al día actual.
2. Se consultan VIIRS SNPP, NOAA20, NOAA21 y MODIS NRT. Son complementarios:
   se intentan los cuatro aunque el primero responda.
3. Si un producto falla, se descarga su CSV oficial de Sudamérica de siete días,
   que no necesita `MAP_KEY`. Se declara el período real de este respaldo: no
   reemplaza ni aparenta cubrir un intervalo histórico anterior.
4. Las nuevas observaciones se unen al histórico conservado. Si hay fallos
   parciales, el estado es `partial`; si fallan todas las fuentes, `offline`.
   Una respuesta válida sin detecciones es `empty`, no una caída ni una prueba
   de ausencia de fuego.
5. La publicación es atómica. Un resultado vacío no borra el histórico.
   Se conserva `.previous` como respaldo. Si el archivo principal se corrompe,
   se sirve el respaldo identificado como tal; en un despliegue nuevo también
   puede usarse la copia incluida en la imagen.

Las peticiones del navegador **no descargan de NASA** y nunca reciben la clave.
El proceso de descarga es independiente y la API solo lee su resultado.

```bash
# Desde wildfire-risk-mlops, con el entorno virtual activo:
python -m src.wildfire.observations build-local
python -m src.wildfire.observations refresh --days 14

# Servicio secundario: actualiza cada hora sin cambiar el servidor web.
python -m src.wildfire.observations watch --days 14 --interval-seconds 3600

# Importar un conjunto histórico explícito; reemplaza el archivo publicado,
# conserva el anterior y deja SHA-256 de cada CSV importado.
python -m src.wildfire.observations build-local --csv archivo1.csv --csv archivo2.csv
```

`build-local` sin argumentos importa los siete CSV consolidados existentes.
No agrega automáticamente la muestra de 250 puntos sin procedencia.
El entrenamiento sigue siendo un flujo separado; actualizar el mapa no
reentrena ni cambia silenciosamente el modelo.

### Servicio secundario opcional con Docker

El comando habitual `docker compose up --build` continúa usando la copia
incluida en la imagen. Para habilitar el actualizador persistente:

```bash
docker compose -f docker-compose.yml -f docker-compose.observations.yml up --build -d
```

El servicio `observations-updater` escribe en un volumen compartido; la API lo
monta en modo de solo lectura. La primera carga usa el archivo incluido mientras
termina la descarga. Configure `MAP_KEY` en `.env` para usar Area API; sin clave
se usan los CSV públicos. Mantenga **una instancia del actualizador** por volumen.
La variable `WILDFIRE_OBSERVATIONS_PATH` permite la misma separación fuera de Docker.
No se ha instalado un servicio del sistema ni activado un despliegue remoto.

## Alternativas y límites

| Alternativa | Uso apropiado | Límite |
| --- | --- | --- |
| Area API multifuente | Actualización incremental por área y fecha | Clave, límites de peticiones y disponibilidad distinta por producto |
| CSV oficial automático | Respaldo simple y sin clave | Ventana móvil de siete días; comparte infraestructura NASA |
| Archivo local válido | Mantener el mapa disponible durante una caída | Antiguo; la fecha debe mostrarse |
| Importación de archivo FIRMS | Recuperar meses/años faltantes | Requiere obtener los archivos y verificar producto/período |
| WMS de FIRMS | Comparación visual con capas oficiales | Una imagen no reemplaza los registros ni permite contarlos con precisión |
| Otra fuente, p. ej. GOES | Análisis complementario independiente | Diferentes resoluciones, horarios y algoritmos; necesita adaptación y validación |
| Scraping HTML | Último recurso si no hay descarga estructurada | Más frágil; no recupera observaciones que el proveedor no publicó |

La implementación elegida evita reescribir la aplicación y no necesita scraping
porque NASA proporciona API y CSV oficiales. No rellena automáticamente **todos
los huecos históricos**: el archivo inicial contiene períodos distintos por
sensor, y `refresh --days 14` recupera la ventana reciente disponible. Una caída
más larga o la comparación de todos los sensores durante años requiere importar
los archivos históricos faltantes. Un día sin registros no demuestra falta de
cobertura ni ausencia de incendios. Las fronteras simplificadas también pueden
excluir puntos muy cercanos al borde; las coordenadas originales se conservan.

Fuentes oficiales consultadas:

- [NASA FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/)
- [NASA FIRMS disponibilidad por producto](https://firms.modaps.eosdis.nasa.gov/api/data_availability/)
- [NASA: uso de FIRMS API y diferencia SP/NRT](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html)
- [NASA: descargas de focos activos](https://firms.modaps.eosdis.nasa.gov/active_fire/)

## Verificación local

- Suite completa: 48 pruebas aprobadas. Se probaron normalización de confianza,
  deduplicación por pasada, filtros, paginación, caída total y parcial,
  respuesta vacía, archivo corrupto y recuperación de la copia válida.
- Navegador: 148.067 detecciones nacionales al elegir todo el archivo; 8.275
  en la última semana. Sin errores JavaScript ni desbordamiento horizontal en
  escritorio/móvil. Se verificaron popups, cambio rápido de filtros y reintento
  tras una respuesta HTTP 503.
- Ruff, sintaxis JavaScript y configuración Compose sin errores.
- El archivo en memoria comparte cadenas repetidas y conserva una sola versión
  en caché. La medición local con modelo cargado bajó de aproximadamente 529 a
  438 MiB de memoria máxima; el consumo dependerá del tamaño futuro del archivo.
- La imagen Docker no se ejecutó en esta sesión: el usuario del entorno no
  tiene acceso al daemon. El servicio opcional queda definido y su configuración
  validada; no se ha iniciado automáticamente ni desplegado en Render.
