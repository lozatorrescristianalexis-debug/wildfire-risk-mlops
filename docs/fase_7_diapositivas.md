# Fase 7: diapositivas listas para trasladar a presentacion

Formato propuesto: 16:9, poco texto, una visualizacion por diapositiva. Los
tiempos suman 14 minutos; el guion oral completo y la demo en ingles estan en
`docs/fase_7_guion_presentacion.md`.

## 1. Wildfire Hotspot Classifier (0:45, Persona 1)

- Madre de Dios, Peru
- NASA FIRMS + Open-Meteo
- Pregunta: ¿que patrones de clima antecedente acompanian detecciones FIRMS?
- No es una alerta ni un pronostico
- **Visual:** mapa de ubicacion con region resaltada (crear desde el bounding
  box/poligono; no sustituir por un mapa de focos ficticio)

## 2. Alcance y etiqueta objetivo (1:00, Persona 1)

- Unidad: celda espacial x dia
- Positiva: al menos una deteccion FIRMS
- Negativa: no deteccion local en un dia con deteccion regional
- Es un proxy de actividad satelital; no confirma ausencia de fuego
- **Visual:** diagrama simple `FIRMS detections -> cell-day label`

## 3. Datos reales integrados (1:15, Persona 1)

- 144 celdas de 0,25 grados
- 43.344 ejemplos, `2024-11-11`–`2026-10-10`
- 2.218 positivos (5,12 %) / 41.126 negativos
- 7.206 detecciones retenidas; cero nulos tras filtros
- **Visual:** `reports/figures/eda_real.png`

## 4. Cobertura FIRMS multifuente (1:00, Persona 2)

- SNPP SP hasta `2026-06-30`; SNPP NRT desde `2026-08-21`
- Gap probado: `2026-07-01`–`2026-08-20`
- Complementos NOAA20 NRT, NOAA21 NRT y MODIS SP/NRT
- Detecciones combinadas en 40/51 dias; 11 dias sin retornos, no “sin fuego”
- **Visual:** timeline preparado desde `reports/firms_gap_alternative_sources.json`;
  mantener cada sensor identificado

## 5. Features y validacion temporal (1:00, Persona 2)

- Clima rezagado: temperatura, humedad, precipitacion y viento
- Medias moviles de 3/7 dias y acumulados de lluvia de 3/7/30 dias
- Sin clima del mismo dia como predictor
- Holdout cronologico: 80 % fechas previas / 20 % fechas recientes
- Optuna TPE: 10 trials por modelo, tres folds temporales expansivos
- **Visual:** esquema de timeline train/test; no mezclar fechas entre bloques

## 6. Modelos comparados (1:30, Persona 2)

| Modelo | F1 test | PR-AUC |
| --- | ---: | ---: |
| Logistic baseline | 0,3485 | 0,2016 |
| Random Forest | 0,5238 | 0,5166 |
| HistGradientBoosting | 0,5090 | 0,4806 |
| XGBoost, seleccionado en OOF temporal | 0,5165 | 0,5110 |

- Seleccion: F1 OOF temporal de XGBoost = 0,4316
- No se selecciono por F1 de test; RF no sustituye al elegido
- **Visual:** `reports/figures/model_comparison_real.png`

## 7. Rendimiento del holdout (1:15, Persona 3)

- Umbral: 0,65327 (seleccionado con predicciones OOF de train)
- F1 0,5165; precision 0,3628; recall 0,8961
- ROC-AUC 0,9279; PR-AUC 0,5110
- Confusion matrix: `[[6828,1196],[79,681]]` (filas reales 0/1)
- **Visual:** `reports/figures/confusion_matrix_real.png` y `roc_pr_real.png`
- Advertencia: la salida describe detecciones FIRMS, no fuego confirmado

## 8. Demo de API (2:15, Persona 3; narracion/operacion en ingles)

- UI English: `https://wildfire-risk-mlops.onrender.com`
- Abrir `GET /health`, `/model-info`, interfaz y Swagger `/docs`
- Ejemplo real: `r013_c007`, `2026-10-10`
- Respuesta: probabilidad 0,07146; threshold 0,65327; clase false
- **Visual:** tabla de la respuesta real; opcional captura del frontend
- Texto oral en ingles, respuestas HTTP y body en
  `docs/fase_7_guion_presentacion.md` y `reports/render_public_smoke.json`

## 9. Arquitectura y operacion (1:30, Persona 4)

- Docker multi-stage: API + frontend + modelo + metadata
- Render Free: auto-deploy desde `main`; posible cold start/sin SLA
- CD: espera Render y prueba health, model-info y predict
- Data: FIRMS/Open-Meteo -> artifact procesado temporal
- Retrain: solo promueve si mejora F1 temporal OOF; monitoring usa PSI
- **Visual:** diagrama de arquitectura de
  `docs/fase_8_informe_tecnico_ti.md`

## 10. Limites, continuidad y cierre (1:30, Persona 4)

- Etiquetas sujetas a cobertura/deteccion de sensor y mezcla documentada
- Desbalance: precision/recall deben leerse juntos
- Sin uso operacional hasta validacion independiente por expertos
- Plan B: Docker local -> evidencias guardadas; identificar capturas previas
- **Visual:** 3 riesgos + 3 mitigaciones; cerrar con “Questions?”

**Fuentes a citar en el pie de las diapositivas:** NASA FIRMS y Open-Meteo
Archive; resultados del proyecto en `reports/real_metrics.json` y fases
documentadas. No agregar porcentajes/figuras que no esten en artefactos reales.
