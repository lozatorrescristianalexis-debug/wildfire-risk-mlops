# Incendios forestales en Madre de Dios, Perú: FIRMS + Open-Meteo

Pipeline de datos y aprendizaje automatico para estudiar detecciones activas de
incendios NASA FIRMS y meteorologia diaria Open-Meteo en el departamento de
Madre de Dios, Peru. El codigo reutilizable esta en `src/wildfire/`; no depende
de notebooks.

> **Importante:** el objetivo implementado es clasificar si FIRMS registro un
> hotspot en una celda durante un dia, usando solo meteorologia de dias previos.
> Es retrospectivo, no un nowcast, pronostico futuro, alerta operativa ni
> estimacion causal del riesgo de incendio. Open-Meteo se consulta en una malla
> espacial, no en un punto representativo. Los negativos se muestrean solo en
> fechas con detecciones en alguna parte del departamento: son un proxy de
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
Copy-Item .env.example .env
```

Abre `.env` localmente y asigna tu clave a `MAP_KEY`. Nunca pegues la clave en
el codigo o en Git. `.env` esta excluido del repositorio. El proyecto lee la
clave directamente desde `<workspace>/.env`.

Opciones de configuracion:

| Variable | Predeterminado | Descripcion |
| --- | --- | --- |
| `MAP_KEY` | vacio | Clave de API de NASA FIRMS; necesaria para `make data`. |
| `FIRMS_SOURCE` | `VIIRS_SNPP_SP` | Coleccion VIIRS de procesamiento estandar para el archivo historico. |
| `FIRMS_AREA` | `-72.4287387,-13.3413977,-68.6519906,-9.9069082` | Bounding box del departamento Madre de Dios en orden `oeste,sur,este,norte`. |
| `METEO_LATITUDE` | `-12.0` | Punto representativo aproximado del centro geografico del departamento. |
| `METEO_LONGITUDE` | `-70.25` | Punto representativo aproximado del centro geografico del departamento. |
| `START_DATE`, `END_DATE` | `2024-10-10`, `2026-10-10` | Periodo `AAAA-MM-DD`; se exige al menos un año. |
| `GRID_CELL_DEGREES` | `0.25` | Resolucion angular de la malla recortada a la frontera administrativa. |

Se eligio Madre de Dios para delimitar el analisis a una sola unidad
administrativa amazonica peruana, evitando mezclar departamentos y climas. La
caja se deriva del bounding box de su relacion administrativa de OpenStreetMap
(relacion [1891287](https://www.openstreetmap.org/relation/1891287)); FIRMS
necesita un rectangulo, que puede incluir pequenas zonas fuera de la frontera.
El punto meteorologico es representativo, no un promedio espacial.

Para otras plataformas, crea el entorno virtual con Python 3.11, instala
`requirements.txt` y ejecuta los mismos comandos Python indicados abajo.

## Comandos

Con el entorno virtual activado:

```text
make data       # 2 años reales de FIRMS + Open-Meteo (requiere MAP_KEY)
make data-demo  # demo aislada: solo para pruebas y tests
make train      # entrena solo datos reales identificados como tales
make run        # score del registro real mas reciente
make test       # pruebas unitarias
```

## API y aplicación web

El servicio FastAPI carga el modelo real y `reports/real_metrics.json` al
iniciar. Ejecuta localmente:

```powershell
docker compose up --build
```

Abre `http://localhost:8000/` para la interfaz (toda en inglés) y
`http://localhost:8000/docs` para Swagger/OpenAPI. Endpoints:

- `GET /health`: estado del servicio y del modelo cargado.
- `GET /model-info`: modelo, periodo, features, umbral y métricas del holdout.
- `POST /predict`: recibe `cell_id`, fecha ISO `date` y un objeto `features`
  con las 13 features numéricas exactas que devuelve `/model-info`.

Predicciones son retrospectivas, no alertas o pronósticos. La tabla web muestra
la probabilidad, el umbral y la celda evaluada.

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
quitando detecciones duplicadas. Open-Meteo consulta la malla en bloques de 30
dias y hasta 50 celdas por peticion, con una pausa minima de cuatro segundos y
reintentos. La ejecucion guarda respuestas originales en `data/raw/` y la tabla
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
etiqueta 0 se conserva solo en dias con alguna deteccion en el departamento,
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
scores. `make run` escribe la clasificacion retrospectiva en la terminal.
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
sus metadatos. El modelo (`models/wildfire_real.joblib`, 402 KB) y
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
[`docs/fase_5.md`](docs/fase_5.md), [`docs/fase_6.md`](docs/fase_6.md),
[`docs/fase_7_guion_presentacion.md`](docs/fase_7_guion_presentacion.md),
[`docs/fase_7_diapositivas.md`](docs/fase_7_diapositivas.md),
[`docs/fase_8_informe_tecnico_ti.md`](docs/fase_8_informe_tecnico_ti.md) y
[`docs/fase_9_auditoria_rubrica.md`](docs/fase_9_auditoria_rubrica.md). El
dataset y los datos crudos se mantienen locales e ignorados; el modelo final y
sus metricas se versionan para que el contenedor sea reproducible. `data-demo`
sigue aislado y no forma parte de estos resultados.
