# Fase 0: alcance y estructura del proyecto

## Alcance asumido

Como no se proporciono un problema distinto, este repositorio se prepara para un
proyecto de aprendizaje automatico sobre incendios forestales con datos de
FIRMS y variables meteorologicas de Open-Meteo. No se descargaron datos ni se
inicio el desarrollo del modelo en esta fase.

## Entorno revisado

Revision realizada en Windows, en `E:\aprendizaje de maquina`.

| Herramienta | Resultado observado |
| --- | --- |
| Python predeterminado | 3.14.6 |
| Python alternativo seleccionado para el proyecto | 3.11 |
| Git | 2.51.2.windows.1 |
| Docker CLI | 29.1.3 |
| Docker Compose | v2.40.3-desktop.1 |
| Motor Docker | No disponible; Docker Desktop no estaba ejecutando su motor |

Python 3.11 se selecciono para el entorno virtual por compatibilidad amplia con
las dependencias fijadas. Git esta instalado y el repositorio local fue
inicializado. Docker CLI esta instalado; para construir imagenes habra que
iniciar Docker Desktop primero. No hace falta reinstalar esas herramientas.
El entorno `.venv` se creo con Python 3.11.0 y las dependencias fijadas se
instalaron correctamente.

## Estructura creada

```text
.
|-- data/
|   |-- processed/
|   `-- raw/
|-- docs/
|-- logs/
|-- models/
|-- notebooks/
|-- reports/figures/
|-- scripts/
|-- src/wildfire/
|-- tests/
|-- .env.example
|-- .gitignore
`-- requirements.txt
```

Los datos originales y los artefactos de modelos quedan fuera de Git. La clave
de FIRMS no se almacena en el codigo ni en el repositorio: `.env.example`
contiene un campo vacio y el archivo local `.env` esta ignorado.

## Comandos y resultados reales

- `python --version` -> Python 3.14.6.
- `python -m pip --version` -> pip 26.2.
- `py -0p` -> Python 3.14, 3.11 y 3.10 disponibles.
- `git --version` -> git version 2.51.2.windows.1.
- `docker --version` -> Docker version 29.1.3, build f52814d.
- `docker compose version` -> Docker Compose version v2.40.3-desktop.1.
- `docker info --format '{{.ServerVersion}}'` -> fallo de conexion al motor;
  no se encontro el pipe de Docker Desktop.
- `git init` -> repositorio inicializado en el workspace.
- `py -3.11 -m venv .venv` -> entorno virtual creado.
- `.venv\Scripts\python.exe -m pip install -r requirements.txt` -> instalacion
  finalizada correctamente para las seis dependencias directas.

## Evidencias

- Configuracion de exclusiones: `.gitignore`.
- Plantilla sin secretos: `.env.example`.
- Dependencias con versiones fijadas: `requirements.txt`.
- Entorno virtual local: `.venv` (ignorado por Git).
- No hay figuras ni logs de experimentos en esta fase.

## Siguiente paso

Crear el entorno virtual, validar la instalacion de dependencias y construir la
primera parte del pipeline de ingesta. No se avanzo a esa fase.
