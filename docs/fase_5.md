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

## Ejecucion observada

La verificacion local de CI se documenta junto con sus resultados finales en
`docs/fase_6.md`. Los workflows se agregaron a la rama `main`; la ejecucion
remota y sus identificadores/estados se reportaran solo despues de consultar
GitHub Actions. Un archivo YAML presente en el repositorio no es evidencia de
una corrida remota.
