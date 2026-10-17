# Fase 3: ejecucion y entrega reproducible

## Entrega

- `README.md`: instalacion, configuracion de claves, fuentes, limites y comandos.
- `Makefile`: atajos `data`, `data-demo`, `train`, `run` y `test`.
- `scripts/run.ps1`: mismos comandos para PowerShell/Windows.
- `Dockerfile` y `.dockerignore`: imagen de ejecucion.

## Resultados reales

- Se ejecuto el flujo PowerShell `data-demo`, `train`, `run` y `test`;
  `pytest` termino con 11 pruebas aprobadas.
- La consulta en vivo Open-Meteo devolvio las 10 filas solicitadas para el
  periodo configurado.
- Docker Desktop se inicio correctamente; `docker build -t wildfire-firms .`
  termino con codigo de salida 0. La ayuda CLI y `data-demo --days 30` tambien
  se probaron dentro del contenedor.
- Se ejecuto el flujo completo aislado en Docker (demo de 1,095 filas,
  entrenamiento, holdout y scoring); termino con codigo de salida 0 y produjo
  las mismas metricas que el entorno virtual.
- `make` y GitHub CLI (`gh`) no estan instalados. El atajo alternativo
  `scripts/run.ps1` si se ejecuto correctamente. No hay remoto Git configurado.
- La ingesta real FIRMS no pudo autenticarse: falta configurar `MAP_KEY` en el
  `.env` local. No se declaran datos FIRMS descargados.

Para publicar el repositorio, crea un repositorio vacio en GitHub y sigue los
comandos `git remote add origin https://github.com/<USUARIO>/<REPO>.git` y
`git push -u origin master`; GitHub CLI no estaba disponible para crear el
remoto desde esta maquina.
