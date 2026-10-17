# Fase 6: plan y resultados de pruebas

## Plan demostrable

Ejecutar desde PowerShell en la raiz:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest --cov=src/wildfire --cov-report=term-missing --cov-report=xml
docker compose config --quiet
docker compose up -d
```

Con Compose arriba, verificar en `http://localhost:8000` `/health`,
`/model-info`, `/predict`, `/openapi.json` y `/`; detener el servicio al acabar
con `docker compose down`.

## Casos y resultados observados

| Caso | Evidencia | Resultado |
| --- | --- | --- |
| Ingesta, parsing, deduplicacion, cache, grilla, lags y origen de sensores | `tests/test_ingest.py` | 12 pruebas pasaron |
| Contrato del modelo, seleccion temporal y rechazo de datos demo | `tests/test_model.py` | 8 pruebas pasaron |
| Health, metadatos, prediccion, rechazo de payload invalido y frontend/OpenAPI | `tests/test_api.py` | 5 pruebas pasaron |
| Deriva de features y rechazo de dataset sintetico | `tests/test_monitor.py` | 2 pruebas pasaron |
| Total pytest | salida de la ejecucion local | 27 pasaron, 0 fallidas |
| Ruff | `ruff check src tests` | sin errores |
| Cobertura pytest-cov | `coverage.xml` local (ignorado por Git) | 61 % total; API 94 %, ingesta 76 %, features 89 % |
| Dependencias | `pip check` | no se encontraron dependencias rotas |
| Compose/YAML | `docker compose config --quiet`; PyYAML sobre 5 workflows | config valida y los 5 YAML parsean |
| Build e integracion HTTP Docker | `reports/docker_http_evidence.json` | build exitoso; cinco rutas HTTP 200; modelo/metadata presentes, `.env` y datos ausentes |

La ejecucion tuvo una advertencia deprecada de Starlette/AnyIO al importar su
cliente de pruebas; no impidio los 27 resultados exitosos. Coverage es 61 %
global, ya que CLI, entrenamiento completo y varias ramas de ingesta no se
ejecutan en la suite unitaria. El coverage XML y `.coverage` son salidas locales
ignoradas; CI publica el resumen en su corrida.

## Smoke test HTTP con el contenedor

La solicitud a `/predict` utilizo los valores climaticos de la fila real
`r013_c007`, `2026-10-10`, y devolvio HTTP 200 con probabilidad `0.0714573`,
umbral `0.6532685` y `predicted_hotspot=false`. `/model-info` devolvio el
modelo XGBoost y metricas reales. Las respuestas completas estan en
`reports/docker_http_evidence.json`; no se usaron datos de demo para esta
prueba.

## Validacion remota

GitHub Actions inicio dos corridas CI al publicar los cambios:

- [CI run 1, 39072309838](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39072309838), commit `2cb1f44`.
- [CI run 2, 39072336776](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39072336776), commit `4dc1903`.

Ambas corridas CI finalizaron `success`, incluidos pytest con cobertura, Ruff,
validacion Compose y build Docker.

La corrida [CD 39072309839](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39072309839)
finalizo con `success` solo para el job de configuracion; el job de despliegue
se omitio porque aun faltaban `HF_TOKEN` y `HF_SPACE`. Por tanto, no se afirma
que hubiera una publicacion en Hugging Face.

No hubo corridas de descarga/reentrenamiento/monitoreo. Para ejecutarlas se
requiere configurar el secret `MAP_KEY`; para despliegue real hacen falta
`HF_TOKEN` y `HF_SPACE`. Los valores se guardan unicamente en Actions.
