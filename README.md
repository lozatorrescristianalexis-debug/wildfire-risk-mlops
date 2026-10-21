# Detecciones de focos de calor en Perú: FIRMS + Open-Meteo

Pipeline de datos y aprendizaje automatico para estudiar detecciones activas de
incendios NASA FIRMS y meteorologia diaria Open-Meteo en todo el Perú.
El codigo reutilizable esta en `src/wildfire/`; no depende
de notebooks.

> **Importante:** el objetivo implementado es clasificar si FIRMS registro un
> hotspot en una celda durante un dia, usando solo meteorologia de dias previos.
> El modelo se validó retrospectivamente. La pantalla inicial puede usar el
> clima estimado de hoy para una inferencia experimental de mañana, pero esa
> salida no tiene validación prospectiva y no es una alerta operativa ni una
> estimación causal del riesgo de incendio. El modelo nacional usa una malla
> de 0,5° para las detecciones y una serie meteorológica representativa por cada
> una de las 25 regiones; el clima local dentro de una región no queda resuelto.
> Los negativos se conservan solo en fechas con detecciones en alguna parte del Perú: son un proxy de
> actividad satelital, no prueba de ausencia de fuego. Las metricas sinteticas
> son unicamente de pruebas y no evidencia del informe final.

## Requisitos

- Python 3.11.
- Para ingesta en vivo: una clave personal gratuita de [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/area/).
- Open-Meteo Archive API se consulta por HTTP; este proyecto no necesita una
  clave de Open-Meteo.
- Docker Desktop solo es necesario para construir/ejecutar la imagen.

## Instalacion en Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
New-Item -ItemType File .env
```

Abre `.env` localmente y asigna tu clave a `MAP_KEY`. Nunca pegues la clave en
el codigo o en Git. `.env` esta excluido del repositorio. El proyecto lee la
clave directamente desde `<workspace>/.env`.

Opciones de configuracion:

| Variable | Predeterminado | Descripcion |
| --- | --- | --- |
| `MAP_KEY` | vacio | Clave de API de NASA FIRMS; necesaria para `make data`. |
| `REGION` | `madre_de_dios` | Región objetivo: `madre_de_dios` o `peru` (nacional). |
| `FIRMS_SOURCE` | `VIIRS_SNPP_SP` | Coleccion VIIRS de procesamiento estandar para el archivo historico. |
| `FIRMS_AREA` | `-72.4287387,-13.3413977,-68.6519906,-9.9069082` | Bounding box en orden `oeste,sur,este,norte` (Perú nacional: `-81.33,-18.35,-68.65,-0.038`). |
| `METEO_LATITUDE` | `-12.0` | Punto representativo aproximado del centro geografico (`-9.19` para Perú). |
| `METEO_LONGITUDE` | `-70.25` | Punto representativo aproximado del centro geografico (`-75.015` para Perú). |
| `START_DATE`, `END_DATE` | `2024-10-10`, `2026-10-10` | Periodo `AAAA-MM-DD`; se exige al menos un año. |
| `GRID_CELL_DEGREES` | `0.25` | Resolucion angular de la malla recortada a la frontera (`0.5` para Perú). |
| `WEATHER_BATCH_SIZE`| `50` | Celdas agrupadas por consulta a Open-Meteo para Madre de Dios; el flujo nacional usa 25 puntos regionales. |
| `WEATHER_CHUNK_DAYS`| `180` | Bloque temporal en días por llamada a Open-Meteo (reduce consultas en un 85%+). |

Por defecto, el proyecto usa Madre de Dios para delimitar el análisis a una sola unidad
administrativa amazónica peruana. Para procesar **todo el Perú**, puedes ejecutar
`make data-peru` o indicar `REGION=peru` (o `--region peru`).

Para otras plataformas, crea el entorno virtual con Python 3.11, instala
`requirements.txt` y ejecuta los mismos comandos Python indicados abajo.

## Comandos

Con el entorno virtual activado:

```text
make data       # 2 años reales para Madre de Dios (o la región definida en .env)
make data-peru  # 2 años reales optimizados para todo el Perú (cobertura nacional)
make data-demo  # demo aislada: solo para pruebas y tests
make train      # entrena solo datos reales identificados como tales
make train-peru # entrena explícitamente el conjunto nacional
make run        # score del registro real mas reciente
make test       # pruebas unitarias
```

## API y aplicación web

El servicio FastAPI carga el modelo real y `reports/real_metrics.json` al
iniciar. Ejecuta localmente:

```powershell
docker compose up --build
```

Abre `http://localhost:8000/` para la interfaz en español y
`http://localhost:8000/docs` para Swagger/OpenAPI. Endpoints:

- `GET /health`: estado del servicio y del modelo cargado.
- `GET /model-info`: modelo, periodo, features, umbral y métricas del holdout.
- `POST /predict`: recibe `cell_id`, fecha ISO `date` y un objeto `features`
  con las 13 features numéricas exactas que devuelve `/model-info`.
- `GET /api/regions`: Perú completo y sus 25 regiones, derivados del GeoJSON local.
- `GET /api/regions-geojson`: límites administrativos usados por los tres mapas.
- `POST /api/predict-grid`: evalúa hasta 2000 muestras, con variables
  meteorológicas completas por muestra o compartidas; rechaza entradas inválidas.
- `GET /api/region-weather`: perfiles históricos observados, secos y húmedos
  para las 25 regiones usados por el mapa.
- `GET /api/live-weather`: clima reciente de Open-Meteo para los 25 puntos
  regionales, con una solicitud agrupada y caché de 15 minutos. Devuelve
  condiciones actuales, resumen diario de hoy y tres perfiles para mañana.
- `GET /api/fire-observations`: detecciones originales del archivo consolidado,
  con filtros por fechas, región, confianza, instrumento y extensión, y paginación
  verificable. Es la fuente del mapa de Observaciones.
- `GET /api/fire-observations/status`: fechas disponibles, fuentes, calidad y
  resultado del último intento de actualización.
- `GET /api/historical-fires`: muestra antigua de 250 puntos, conservada por
  compatibilidad; ya no alimenta el mapa de Observaciones.

La tabla web muestra la probabilidad, el umbral y la celda evaluada. La fecha
identifica el caso, pero no es una variable del modelo. El panorama ofrece
cuatro modos: clima de hoy, día lluvioso simulado, día caluroso simulado y
fecha histórica de referencia. Los tres primeros usan las condiciones de hoy
y 29 días anteriores para evaluar **mañana**, porque el modelo fue entrenado
con variables meteorológicas anteriores al día objetivo. El día de hoy incluye
un pronóstico diario de Open-Meteo para las horas que aún no transcurren; sus
condiciones actuales también provienen de modelos meteorológicos. El escenario
lluvioso fija al menos 20 mm de lluvia y 85 % de humedad y reduce 2 °C la
temperatura máxima de hoy; el caluroso sube 4 °C, reduce 15 puntos de humedad
y elimina la lluvia de hoy. Son comparaciones hipotéticas, no pronósticos de
incendios. Si Open-Meteo falla, la vista histórica permanece disponible.
La superficie entre muestras se
interpola solo para visualizarla y se recorta al límite regional. Los indicadores
cuentan únicamente centros de muestreo dentro de la región; «sobre el umbral»
usa el corte calibrado del modelo. La malla visual nacional usa muestras a
intervalos de 0,35°; el entrenamiento emplea celdas de 0,5° y clima de 25
puntos regionales. Al hacer clic en el mapa se calcula un valor
exacto para esa coordenada, sin tomar el color interpolado como predicción.
El modelo desplegado fue entrenado con datos del Perú completo y se evaluó con
un holdout temporal nacional. El panel informa métricas regionales cuando hay
ejemplos de ambas clases; las regiones sin muestra suficiente no reciben una
métrica local. El mapa de observaciones usa el archivo consolidado
`web/fire_observations.json.gz`, con coordenadas y horas de adquisición originales.
La región se calcula por coordenadas; los puntos fuera de Perú se excluyen del
mapa nacional y pueden consultarse con `region=all`. El archivo disponible no
garantiza cobertura completa de todos los sensores y períodos de FIRMS.

Para actualizarlo, ejecuta `python -m src.wildfire.observations refresh --days 14`.
Un servicio independiente opcional (`observations watch`) combina cuatro
productos FIRMS, usa CSV oficiales como respaldo y conserva la última descarga
válida. El modelo y el servidor web no necesitan cambiar. Consulta
[diagnóstico, comandos y alternativas de recuperación](docs/mapa_datos.md),
incluido el archivo Docker Compose opcional para actualización automática.

Los límites provienen de [geoBoundaries gbOpen Perú ADM1](https://www.geoboundaries.org/api/current/gbOpen/PER/ADM1/)
(William & Mary geoLab; fuente original: Wikimedia Commons). El archivo local
`web/peru_regions.geojson` incluye 25 regiones: Lima Metropolitana se une a
Lima y Callao se mantiene como región separada. El selector, las extensiones
del mapa y la resolución de la malla se calculan desde ese archivo, sin
consultas externas en cada visita. Para actualizarlo, ejecuta
`python scripts/update_regions.py` y revisa el GeoJSON resultante.

La interfaz usa HTML, CSS, JavaScript y Leaflet sin fase de compilación.
FastAPI sirve los archivos desde `web/` y el Dockerfile los copia en la
imagen, de modo que Render puede seguir construyendo el mismo servicio Docker.
La API pública de Open-Meteo no requiere clave para prototipos no comerciales;
su [licencia gratuita excluye uso comercial](https://open-meteo.com/en/pricing).
Una aplicación comercial debe usar su plan correspondiente o alojar un
proveedor meteorológico propio.

En Windows, si no tienes GNU Make, los mismos atajos estan disponibles en
PowerShell:

```powershell
.\scripts\run.ps1 data-demo
.\scripts\run.ps1 train
.\scripts\run.ps1 run
.\scripts\run.ps1 test
```

Tambien puedes invocar directamente `python -m src.wildfire.cli` con uno de
estos subcomandos: `data`, `data-demo`, `train` o `run`.

## Ingesta y formato

`make data` descarga el periodo historico predeterminado de dos años. FIRMS usa
`VIIRS_SNPP_SP`; el historico se descarga en bloques de hasta cinco dias, con
hasta cuatro trabajadores y un limitador global de una solicitud por segundo
(aprox. 147 solicitudes para dos años, muy por debajo del limite de 5.000
transacciones por 10 minutos). Los bloques se guardan atomicamente y se
reutilizan al reanudar. El tramo NRT reciente se consulta aparte y se combina
quitando detecciones duplicadas. En el flujo nacional, Open-Meteo aporta una
serie diaria por cada una de las 25 regiones y las celdas heredan el clima de
la región que más superficie comparte con ellas. La resolución climática es
regional; no permite distinguir microclimas dentro de una región. El cliente
limita la frecuencia de solicitudes, reutiliza la caché y divide periodos si
la API responde 429. La ejecucion guarda respuestas originales en `data/raw/` y la tabla
celda-dia unida en `data/processed/real_daily.csv`. Los
errores de red, autenticacion o respuesta incompleta detienen la ingesta; no se
crean etiquetas ni clima sinteticos para reemplazar fallos. Como alternativa,
proporciona un CSV FIRMS real ya descargado:

```text
python -m src.wildfire.cli data --firms-csv data/raw/fires.csv
```

El CSV debe contener `acq_date`, `latitude` y `longitude`. El periodo efectivo
se configura en `.env`; la ingesta se detiene si es menor de un año. No
etiquetes como ausencia de fuego un dia sin cobertura satelital adecuada.

La etiqueta 1 significa que una celda tuvo al menos una deteccion FIRMS. La
etiqueta 0 se conserva solo en dias con alguna deteccion en el área de estudio,
para limitar los negativos a fechas con actividad observada; aun asi no implica
que el satelite haya sobrevolado la celda ni confirma ausencia de fuego.

El conjunto real de celda-dia se guarda en `data/processed/real_daily.csv`,
ignorado por Git. Incluye `date`, `cell_id`, `fire_count`, `label`, variables
climaticas con rezagos, medias moviles y acumulados de precipitacion,
coordenadas, `firms_sources` para atribuir sensores, `data_source=firms_open_meteo`
y la definicion del negativo.

## Modelo, metricas y ejecucion

El entrenamiento final exige una fuente `firms_open_meteo`, al menos un año,
ambas clases en train y test y una particion cronologica 80/20. La demo esta
marcada como `synthetic_demo` y el entrenador de CLI la rechaza. El modelo real
se guarda en `models/wildfire_real.joblib` y sus metricas en
`reports/real_metrics.json`. Las metricas incluyen balance de clase completo y
del holdout, intervalo de fechas, numero de detecciones, confusion matrix y
scores. El artefacto nacional vigente se entrenó con 350.192 registros de
celda-día. En el holdout temporal del 22 de mayo al 10 de octubre de 2026
obtuvo F1 0,497, precisión 0,404, recall 0,646 y PR-AUC 0,459. La calibración
logística con predicciones temporales fuera de pliegue redujo el Brier del
holdout de 0,196 a 0,115; el umbral calibrado es 0,175. Las métricas
regionales se calculan con el mismo umbral nacional: 24 regiones tienen ambas
clases; Callao no tiene centro de celda propio en esta malla de 0,5°. En Tacna,
Arequipa y Puno el F1 regional es inferior a 0,2. Estas cifras describen
detecciones satelitales retrospectivas, no un pronóstico de incendios.
`make run` escribe la clasificacion retrospectiva en la terminal.
El artefacto vigente del modelo y su metadata se versionan para poder construir
la API y la imagen de produccion desde un clone; artefactos de otros modelos,
datasets y datos crudos permanecen ignorados.

`make data-demo` guarda datos unicamente en `data/demo/daily.csv`. Sirve para
pruebas automatizadas y verificar que el CLI funciona sin secretos. `make train`
y `make run` nunca usan esa ruta, y `train_model` rechaza esa etiqueta de origen
por defecto. No uses ni transcribas las antiguas metricas demo de
`docs/fase_2.md` al informe.

## Docker

El build es multi-stage y copia solo codigo, web, el modelo real versionado y
sus metadatos. El modelo (`models/wildfire_real.joblib`, aproximadamente 476 KB) y
`reports/real_metrics.json` se versionan deliberadamente como artefactos de
despliegue pequenos y reproducibles; los demas modelos siguen ignorados. Los
datos procesados locales, todos los crudos de `data/raw/`, `.env` y claves no se
copian a la imagen ni se suben a Git. Asi el contenedor no depende de un volumen
local, registro de modelos externo o credenciales para cargar el modelo.

Con Docker Desktop ejecutandose:

```powershell
docker build -t wildfire-firms .
docker run --rm -p 8000:7860 wildfire-firms
```

Para desarrollo local se recomienda `docker compose up --build`; abre
`http://localhost:8000` y supervisa `/health`.

## Despliegue publico

La aplicacion esta desplegada como **Render Web Service / Docker / Free** en
[`https://wildfire-risk-mlops.onrender.com`](https://wildfire-risk-mlops.onrender.com).
Render hace auto-deploy desde `main`; el workflow `cd.yml` no vuelve a publicar
la imagen, sino que espera a que el despliegue termine y prueba `/health`,
`/model-info` y `/predict` con una fila real. El servicio gratuito puede dormir;
el workflow permite un tiempo de conexion de 15 segundos, timeout de respuesta
de 75 segundos y hasta 12 intentos separados por 10 segundos.

En GitHub Actions configura la variable `APP_URL` con la URL publica completa
del Web Service. Para descarga automatica de FIRMS, agrega `MAP_KEY` como
secret (nunca como variable visible). `retrain.yml` y `monitoring.yml` pueden
ejecutarse manualmente especificando `data_run_id` de una ejecucion exitosa de
`Refresh real FIRMS data`; tambien se disparan despues de una descarga exitosa.

La imagen runtime copia el codigo, la UI, el modelo y sus metadatos, pero no
incluye `.env`, `data/raw/` ni `data/processed/`. El workflow de datos transfiere
el CSV integrado unicamente como artifact temporal de Actions, nunca los
archivos crudos.

## Publicar en GitHub

El repositorio de este workspace ya esta conectado a `origin/main`. En un clone
nuevo, configura un remoto HTTPS sin token embebido y publica la rama `main`:

```powershell
git remote add origin https://github.com/<USUARIO>/<REPO>.git
git push -u origin main
```

Git usara el mecanismo de autenticacion configurado en tu equipo. No pongas
tokens en la URL del remoto. Sustituye `<USUARIO>/<REPO>` por la URL que GitHub
muestre al crear el repositorio.

## Estructura

```text
src/wildfire/   Configuracion, ingesta real, generacion demo aislada, modelo y CLI
tests/          Pruebas unitarias
data/raw/       Entrada local; ignorada por Git
data/processed/ Dataset diario real; ignorado por Git
data/demo/      Datos sinteticos exclusivos de pruebas; ignorados por Git
models/         wildfire_real.joblib versionado; otros modelos ignorados
reports/        real_metrics.json versionado; figuras y resultados locales
notebooks/      Analisis opcional; la logica reutilizable vive en src/
docs/fase_*.md  Alcance, comandos y resultados observados por fase
```

## Resultados de la ejecucion real

La ejecucion real multifuente produjo 43.344 ejemplos celda-dia (2.218 positivos) entre
`2024-11-11` y `2026-10-10`; el holdout temporal de XGBoost obtuvo F1 `0.5165`,
precision `0.3628`, recall `0.8961`, ROC-AUC `0.9279` y PR-AUC `0.5110`.
FIRMS devolvio detecciones SP hasta `2026-06-30` y NRT desde `2026-08-21`;
fuentes NOAA20/NOAA21 NRT y MODIS aportaron detecciones en 40 de los 51 dias
del intervalo `2026-07-01`–`2026-08-20`; los productos permanecen identificados
por sensor y 11 dias no tuvieron detecciones devueltas. Los resultados son
retrospectivos y no un pronostico. El resumen
detallado, la matriz de confusion y las figuras estan en
[`docs/fase_1.md`](docs/fase_1.md), [`docs/fase_2.md`](docs/fase_2.md),
[`docs/fase_3.md`](docs/fase_3.md), [`docs/fase_4.md`](docs/fase_4.md),
[`docs/fase_5.md`](docs/fase_5.md) y [`docs/fase_6.md`](docs/fase_6.md). El
dataset y los datos crudos se mantienen locales e ignorados; el modelo final y
sus metricas se versionan para que el contenedor sea reproducible. `data-demo`
sigue aislado y no forma parte de estos resultados.

## Auditoría regional de Puno

El mapa actualizado y el dataset de entrenamiento tienen ciclos distintos.
`/model-info` informa filas de ajuste, filas de prueba y sus períodos; descargar
observaciones no reentrena. Se implementó una comparación reproducible entre
umbral regional y modelos especializados, guardando el candidato separado del
modelo servido. Consulta [datos usados, resultados y limitaciones en Puno](docs/puno_modelo.md)
o ejecuta `python -m src.wildfire.regional_experiment`.


### Corrección prioritaria de entrenamiento en Puno

El flujo `data --region peru` mantiene un satélite a lo largo del período (SP y
NRT según disponibilidad) y descarga clima por centro de celda para Puno.
`python -m src.wildfire.priority_experiment --trials 5` construye y evalúa un
candidato aislado, con el mismo corte temporal de la versión anterior.
La ejecución del 21/10/2026 mejoró PR-AUC, pero no F1 en Puno; el candidato quedó
sin activar y la API conserva el modelo anterior. El detalle reproducible está
en [docs/puno_modelo.md](docs/puno_modelo.md) y
[reports/priority_improvement.json](reports/priority_improvement.json).
Las métricas regionales se consultan ahora en un desplegable del panel del modelo.
