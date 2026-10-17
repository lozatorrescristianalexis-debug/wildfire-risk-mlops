# Incendios forestales: FIRMS + Open-Meteo

Pipeline didactico de datos y aprendizaje automatico para relacionar
detecciones activas de incendios de NASA FIRMS con meteorologia diaria de
Open-Meteo. El codigo reutilizable esta en `src/wildfire/`; no depende de
notebooks.

> **Importante:** el objetivo implementado es detectar si FIRMS registro un
> hotspot en un dia usando meteorologia diaria de ese mismo dia. Es una
> demostracion de clasificacion retrospectiva, no un nowcast, pronostico futuro,
> alerta operativa ni estimacion causal del riesgo de incendio. Open-Meteo usa un
> unico punto representativo del area, no datos meteorologicos de toda la
> region. Las metricas de datos sinteticos no son evidencia de desempeno real.

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
el codigo o en Git. `.env` esta excluido del repositorio.

Opciones de configuracion:

| Variable | Predeterminado | Descripcion |
| --- | --- | --- |
| `MAP_KEY` | vacio | Clave de API de NASA FIRMS; necesaria para `make data`. |
| `FIRMS_SOURCE` | `VIIRS_SNPP_NRT` | Coleccion FIRMS activa. |
| `FIRMS_AREA` | `-5,36,4,44` | Area `oeste,sur,este,norte` (longitudes y latitudes). |
| `METEO_LATITUDE` | `40.4168` | Latitud del punto meteorologico representativo. |
| `METEO_LONGITUDE` | `-3.7038` | Longitud del punto meteorologico representativo. |
| `START_DATE`, `END_DATE` | ultimos diez dias | Periodo de descarga, formato `AAAA-MM-DD`; la API FIRMS devuelve solo sus diez dias mas recientes. Para fechas historicas usa `--firms-csv`. |

Para otras plataformas, crea el entorno virtual con Python 3.11, instala
`requirements.txt` y ejecuta los mismos comandos Python indicados abajo.

## Comandos

Con el entorno virtual activado:

```text
make data       # FIRMS + Open-Meteo (requiere MAP_KEY)
make data-demo  # datos sinteticos reproducibles, sin red ni secretos
make train      # entrenamiento y evaluacion cronologica 80/20
make run        # probabilidad de hotspot para la fila mas reciente
make test       # pruebas unitarias
```

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

`make data` obtiene los hotspots de FIRMS para el area configurada y el clima
diario del punto representativo en Open-Meteo. Como alternativa, proporciona un
CSV FIRMS ya descargado:

```text
python -m src.wildfire.cli data --firms-csv data/raw/fires.csv
```

El CSV debe contener `acq_date` (o `scan_date`/`date`). La descarga de area de
FIRMS solo cubre hasta diez dias; un conjunto tan corto puede no ser suficiente
para entrenar. Para entrenar con datos reales, prepara un historial FIRMS con
cobertura consistente, configura un periodo compatible y consulta las
limitaciones y licencias de los proveedores. No etiquetes como ausencia real
un dia que carezca de cobertura satelital.

El conjunto diario se guarda en `data/processed/daily.csv`, ignorado por Git.
Columnas: `date`, `fire_count`, `label`, `temperature_2m_max`,
`relative_humidity_2m_mean`, `precipitation_sum`, `wind_speed_10m_max`,
`latitude` y `longitude`.

## Modelo, metricas y ejecucion

El entrenamiento exige ambas clases en train y test y usa una particion
cronologica, sin mezclar el futuro con el pasado. El modelo se guarda en
`models/wildfire.joblib` y las metricas/intervalo evaluado en
`reports/metrics.json`. `make run` escribe el resultado JSON en la terminal.
Datos, modelos y logs generados no se versionan.

`make data-demo` construye un conjunto determinista sintetico para validar
instalacion y ejecucion sin clave. Etiquetas, puntuaciones y metricas de este
conjunto no deben presentarse como resultados con datos reales.

## Docker

Con Docker Desktop ejecutandose:

```powershell
docker build -t wildfire-firms .
docker run --rm wildfire-firms --help
docker run --rm wildfire-firms data-demo --days 30
```

La imagen expone el CLI como entrypoint. El segundo comando es un smoke test
aislado: `--rm` elimina sus datos al terminar. Para conservar datos o usar
credenciales, monta las carpetas y pasa la configuracion de forma segura; no
incluyas `.env` en la imagen.

## Publicar en GitHub

Tras crear un repositorio vacio en GitHub (sin README ni licencia inicial),
conecta y publica esta rama:

```powershell
git remote add origin https://github.com/<USUARIO>/<REPO>.git
git push -u origin master
```

Git usara el mecanismo de autenticacion configurado en tu equipo. No pongas
tokens en la URL del remoto. Sustituye `<USUARIO>/<REPO>` por la URL que GitHub
muestre al crear el repositorio.

## Estructura

```text
src/wildfire/   Configuracion, ingesta, generacion demo, modelo y CLI
tests/          Pruebas unitarias
data/raw/       Entrada local; ignorada por Git
data/processed/ Datos derivados; ignorados por Git
models/         Modelos entrenados; ignorados por Git
reports/        Metricas y figuras
notebooks/      Analisis opcional; la logica reutilizable vive en src/
docs/fase_*.md  Alcance, comandos y resultados observados por fase
```

## Resultados del entorno de desarrollo

Consulta [docs/fase_0.md](docs/fase_0.md), [docs/fase_1.md](docs/fase_1.md),
[docs/fase_2.md](docs/fase_2.md) y [docs/fase_3.md](docs/fase_3.md) para
resultados reales, evidencia y limitaciones de cada fase.
