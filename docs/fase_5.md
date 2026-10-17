# Fase 5: automatizacion y monitoreo

## Workflows implementados

- `.github/workflows/ci.yml`: Ruff, pytest con informe de cobertura, validacion
  de Compose y build Docker.
- `.github/workflows/cd.yml`: despliega una lista permitida al Hugging Face
  Space configurado en `HF_SPACE` y prueba `/health`. Si faltan ajustes, emite
  una anotacion visible y no intenta publicar.
- `.github/workflows/data_update.yml`: ejecucion semanal o manual; exige el
  secret `MAP_KEY`, descarga solo datos reales, y entrega dataset procesado e
  informes como artifact temporal de Actions (sin archivos de `data/raw/`).
- `.github/workflows/retrain.yml`: se activa tras una descarga exitosa, usa el
  dataset procesado del artifact, compara F1 de validacion temporal OOF y solo
  hace commit/push de dataset y artefactos si el candidato mejora estrictamente.
- `.github/workflows/monitoring.yml`: tras la descarga valida, compara 30 dias
  recientes contra 90 de referencia; guarda PSI por feature y cambio de tasa
  positiva como artifact. PSI >= 0,20 es una senal de revision, no un diagnostico.

`src/wildfire/monitor.py` se niega a procesar origen sintetico o combinado,
requiere fechas y features finitas y falla si las ventanas son insuficientes.
Los eventos de prediccion del servicio registran celda, fecha, score y umbral,
sin registrar credenciales ni features detalladas.

## Requisitos de secretos

La cuenta de Hugging Face y las variables/secrets del repositorio no estaban
configurados en el entorno al implementar esta fase. Se requieren:

- GitHub Actions secret `MAP_KEY` para actualizar los datos.
- GitHub Actions secret `HF_TOKEN` y variable `HF_SPACE` para desplegar.

Los valores solo se configuran en Settings > Secrets and variables > Actions;
no se solicitan ni se guardan en el repo. El workflow CD deja una anotacion
explicita cuando no se configura el destino. La descarga/reentrenamiento
requieren el secret FIRMS y no se reportan aqui como ejecuciones completadas.

## Ejecucion observada en GitHub Actions

GitHub Actions registra los cinco workflows como activos. Tras publicar los
cambios, la corrida CD **39072309839** termino `success`; su job
`deployment-configuration` paso y `deploy` quedo `skipped`, por lo que no hubo
despliegue remoto. El log publico indica que faltan `HF_SPACE` y `HF_TOKEN`.

Las corridas CI **39072309838** (run 1, commit `2cb1f44`) y **39072336776**
(run 2, commit `4dc1903`) terminaron `success`: en ambas completaron
instalacion, Ruff, pytest con cobertura, validacion Compose y build Docker.
No se encontraron corridas de `data_update.yml`, `retrain.yml` ni
`monitoring.yml`: las dos ultimas dependen de una descarga exitosa y el refresh
requiere el secret `MAP_KEY`.

Enlaces de las corridas consultadas:

- [CD 39072309839](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39072309839)
- [CI 39072309838](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39072309838)
- [CI 39072336776](https://github.com/lozatorrescristianalexis-debug/wildfire-risk-mlops/actions/runs/39072336776)

La verificacion local de CI y pruebas se documenta en `docs/fase_6.md`.
