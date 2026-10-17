# Incendios forestales en Madre de Dios, Perú: FIRMS + Open-Meteo

Pipeline de datos y aprendizaje automatico para estudiar detecciones activas de
incendios NASA FIRMS y meteorologia diaria Open-Meteo en el departamento de
Madre de Dios, Peru. El codigo reutilizable esta en `src/wildfire/`; no depende
de notebooks.

> **Importante:** el objetivo implementado es detectar si FIRMS registro un
> hotspot en un dia usando meteorologia diaria de ese mismo dia. Es una
> demostracion de clasificacion retrospectiva, no un nowcast, pronostico futuro,
> alerta operativa ni estimacion causal del riesgo de incendio. Open-Meteo usa un
> unico punto representativo del departamento, no datos meteorologicos de toda
> el area. La ausencia de detecciones FIRMS no prueba ausencia de incendios; la
> cobertura depende de los sensores. Las metricas sinteticas son unicamente de
> pruebas y no son evidencia del informe final.

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
| `START_DATE`, `END_DATE` | 2 años completos hasta hace 7 dias (UTC) | Periodo `AAAA-MM-DD`; se exige al menos un año. |

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
`VIIRS_SNPP_SP`; el historico se descarga en solicitudes secuenciales de un
maximo de cinco dias (aprox. 147 solicitudes para dos años), conservador respecto
a los limites del endpoint. Open-Meteo se
consulta en bloques de 30 dias. La ejecucion guarda respuestas originales en
`data/raw/` y la tabla diaria unida en `data/processed/real_daily.csv`. Los
errores de red, autenticacion o respuesta incompleta detienen la ingesta; no se
crean etiquetas ni clima sinteticos para reemplazar fallos. Como alternativa,
proporciona un CSV FIRMS real ya descargado:

```text
python -m src.wildfire.cli data --firms-csv data/raw/fires.csv
```

El CSV debe contener `acq_date`, `latitude` y `longitude`. El periodo efectivo
se configura en `.env`; la ingesta se detiene si es menor de un año. No
etiquetes como ausencia de fuego un dia sin cobertura satelital adecuada.

La clase 1 significa "al menos una deteccion activa FIRMS en ese dia y
rectangulo"; clase 0 significa "ninguna deteccion devuelta". No es una verdad
terrestre completa sobre igniciones/incendios, por limitaciones de paso
satelital, nubes y resolucion.

El conjunto real se guarda en `data/processed/real_daily.csv`, ignorado por Git.
Columnas: `date`, `fire_count`, `label`, `temperature_2m_max`,
`relative_humidity_2m_mean`, `precipitation_sum`, `wind_speed_10m_max`,
`latitude`, `longitude` y `data_source=firms_open_meteo`.

## Modelo, metricas y ejecucion

El entrenamiento final exige una fuente `firms_open_meteo`, al menos un año,
ambas clases en train y test y una particion cronologica 80/20. La demo esta
marcada como `synthetic_demo` y el entrenador de CLI la rechaza. El modelo real
se guarda en `models/wildfire_real.joblib` y sus metricas en
`reports/real_metrics.json`. Las metricas incluyen balance de clase completo y
del holdout, intervalo de fechas, numero de detecciones, confusion matrix y
scores. `make run` escribe la clasificacion retrospectiva en la terminal.
Datos, modelos y metricas generadas no se versionan.

`make data-demo` guarda datos unicamente en `data/demo/daily.csv`. Sirve para
pruebas automatizadas y verificar que el CLI funciona sin secretos. `make train`
y `make run` nunca usan esa ruta, y `train_model` rechaza esa etiqueta de origen
por defecto. No uses ni transcribas las antiguas metricas demo de
`docs/fase_2.md` al informe.

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
src/wildfire/   Configuracion, ingesta real, generacion demo aislada, modelo y CLI
tests/          Pruebas unitarias
data/raw/       Entrada local; ignorada por Git
data/processed/ Dataset diario real; ignorado por Git
data/demo/      Datos sinteticos exclusivos de pruebas; ignorados por Git
models/         Modelos entrenados; ignorados por Git
reports/        Metricas y figuras
notebooks/      Analisis opcional; la logica reutilizable vive en src/
docs/fase_*.md  Alcance, comandos y resultados observados por fase
```

## Resultados del entorno de desarrollo

Consulta [docs/fase_0.md](docs/fase_0.md), [docs/fase_1.md](docs/fase_1.md),
[docs/fase_2.md](docs/fase_2.md), [docs/fase_3.md](docs/fase_3.md) y
[docs/fase_4.md](docs/fase_4.md) para evidencia y limitaciones. Solo
`reports/real_metrics.json` debe usarse para el informe, y solo despues de
completar una ingesta real verificable.
