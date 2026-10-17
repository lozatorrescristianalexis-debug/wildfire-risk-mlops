# Fase 7: guion de sustentacion (12–15 minutos, 4 personas)

**Duracion objetivo:** 14 minutos. **Idioma:** presentacion en espanol; la
demostracion de la interfaz y los endpoints se narra en ingles, igual que la UI.
Las cifras corresponden al modelo real disponible al 2026-10-17; no leerlas
como promesa de desempeño futuro.

## Reparto y diapositivas

| Slide | Tiempo | Persona | Contenido / apoyo visual |
| --- | ---: | --- | --- |
| 1. Problema y alcance | 0:45 | 1 | Titulo, Madre de Dios y pregunta de trabajo |
| 2. Objetivo y limites | 1:00 | 1 | Clasificacion retrospectiva, no forecast/alerta |
| 3. Datos reales | 1:15 | 1 | Mapa esquematico del area, FIRMS + Open-Meteo |
| 4. Brecha de sensores y etiquetas | 1:00 | 2 | Timeline de cobertura y clases |
| 5. Features y control de fuga | 1:00 | 2 | Rezagos, ventanas moviles y split cronologico |
| 6. Comparacion de modelos | 1:30 | 2 | Tabla F1/PR-AUC de los cuatro modelos |
| 7. Resultado del holdout | 1:15 | 3 | Confusion matrix, umbral, precision/recall |
| 8. API y app web (English demo) | 2:15 | 3 | Formulario, tabla de salida y endpoints |
| 9. Docker, Render y automatizacion | 1:30 | 4 | Arquitectura y CI/CD/data workflows |
| 10. Limitaciones, plan B y cierre | 1:30 | 4 | Riesgos, trabajo siguiente, preguntas |
| **Total** | **14:00** | | |

## Guion por persona

### Persona 1 — Contexto y datos (slides 1–3, 3:00)

**Slide 1 (0:45).** “Nuestro proyecto integra observaciones satelitales de
NASA FIRMS y variables meteorologicas de Open-Meteo para estudiar actividad de
hotspots en celdas de Madre de Dios. La pregunta concreta es si, usando el
clima observado antes del dia objetivo, podemos clasificar una celda-dia
similar a una deteccion FIRMS.”

**Slide 2 (1:00).** “Es importante delimitar el alcance: esto es clasificacion
retrospectiva de detecciones satelitales, no pronostico de incendios, alerta
operativa ni causalidad. Una prediccion negativa no certifica que no hubiera
fuego. La etiqueta negativa significa que no recibimos deteccion en esa celda
en un dia con actividad detectada en la region.”

**Slide 3 (1:15).** “La region es el departamento de Madre de Dios, Peru, con
144 celdas. Usamos datos FIRMS y clima diario real; despues de los rezagos, el
dataset modelable tiene 43.344 observaciones entre 11 de noviembre de 2024 y
10 de octubre de 2026. Hay 2.218 positivas y 41.126 negativas, una prevalencia
positiva de 5,12 por ciento.”

### Persona 2 — Calidad de datos y modelo (slides 4–6, 3:30)

**Slide 4 (1:00).** “El producto estandar VIIRS SNPP cubrio hasta el 30 de
junio de 2026 y el NRT desde el 21 de agosto. Intentamos cubrir la brecha del
1 de julio al 20 de agosto con cinco productos alternativos: hubo detecciones
en 40 de 51 dias combinando NOAA20, NOAA21 y MODIS. Once dias no devolvieron
detecciones; no los interpretamos como ausencia de fuego. Guardamos
`firms_sources` para conservar procedencia del sensor.”

**Slide 5 (1:00).** “Las features incluyen temperatura, humedad, viento y
precipitacion con rezagos, medias moviles y acumulados; no se usa el clima del
mismo dia como predictor. El holdout separa por fecha ascendente: 80 por ciento
de fechas activas para train y 20 por ciento mas recientes para test. Optuna
ajusto cada familia sobre tres folds temporales expansivos; el holdout no se
uso para elegir el modelo ni el umbral.”

**Slide 6 (1:30).** “Comparamos baseline logistico, Random Forest,
HistGradientBoosting y XGBoost, con diez trials Optuna cada uno. El modelo
seleccionado fue XGBoost por F1 out-of-fold temporal de entrenamiento de
0,4316; no por el score de test. En test, F1 fue 0,5165 y PR-AUC 0,5110.
Random Forest obtuvo F1 de test ligeramente mayor, 0,5238, pero elegirlo por
ese resultado habria usado el holdout para seleccion, por eso informamos
XGBoost como elegido por validacion temporal.”

### Persona 3 — Evaluacion y demo funcional (slides 7–8, 3:30)

**Slide 7 (1:15).** “La tasa positiva del holdout es 760 de 8.784 filas.
Con umbral 0,65327, XGBoost alcanzo precision 0,3628, recall 0,8961,
ROC-AUC 0,9279 y PR-AUC 0,5110. La matriz, con filas de clase real 0 y 1 y
columnas predichas 0 y 1, es [[6828,1196],[79,681]]. Accuracy no es nuestra
metrica principal por el desbalance.”

**Slide 8 — demo en ingles (2:15).** Cambiar a la pagina desplegada y mostrar
la tabla/formulario. Texto sugerido, en ingles:

> “This is the Wildfire Hotspot Classifier for Madre de Dios. It performs a
> retrospective cell-day classification; it is not a fire forecast or an
> operational alert. I will score the real grid-cell observation
> `r013_c007` for `2026-10-10`, using lagged weather features from our real
> dataset. The API returns a hotspot probability of about 7.15 percent, with
> a decision threshold of about 65.33 percent, so the model classifies this
> example as no hotspot detected. The threshold is a validation-selected
> operating point, not a safety boundary. The same service exposes
> `/health`, `/model-info`, and `/predict`, with request validation documented
> in Swagger.”

Mostrar tambien `GET /health` como servicio vivo y abrir `/docs` brevemente.
No afirmar que un score individual sea evidencia de incendio o ausencia.

### Persona 4 — Operacion, limites y cierre (slides 9–10, 3:00)

**Slide 9 (1:30).** “Empaquetamos API, frontend, modelo y metadatos en una
imagen Docker multi-stage; la imagen no incluye `.env`, datos crudos ni dataset
procesado. Render ejecuta el contenedor en plan Free y hace auto-deploy desde
`main`. GitHub Actions corre CI —Ruff, pytest con cobertura, Compose y build—
y el CD espera Render y prueba una prediccion real. La ingesta semanal necesita
el secret `MAP_KEY`; reentrenamiento y monitoreo trabajan sobre el artifact
procesado de una corrida de datos.”

**Slide 10 (1:30).** “Las principales limitaciones son el sesgo de deteccion y
cobertura satelital, la mezcla documentada de sensores en la brecha, el
desbalance y el comportamiento de cold start/cuotas del plan gratuito. El
siguiente paso operativo es validar con expertos y datos independientes antes
de cualquier uso de respuesta a emergencias. Gracias; quedamos atentos a sus
preguntas.”

## Plan B de demostracion

1. Abrir de antemano `https://wildfire-risk-mlops.onrender.com` y permitir el
   cold start; tener listo `/health`, `/model-info` y `/docs`.
2. Si Render no despierta o falla la red, ejecutar `docker compose up -d` en el
   equipo preparado, probar `http://localhost:8000/health` y usar la misma
   request guardada en `reports/api_http_evidence.json`.
3. Si tampoco hay Docker/red, presentar capturas/respuestas guardadas en
   `reports/render_public_smoke.json` y `reports/docker_http_evidence.json`.
   Identificarlas explicitamente como evidencia previa, no como una ejecucion
   en vivo.
4. No improvisar una prediccion con valores aleatorios; mantener la fila real
   `r013_c007`, `2026-10-10`.

## 15 preguntas probables y respuestas

1. **¿Esto predice un incendio futuro?** No. Clasifica retrospectivamente una
   deteccion FIRMS por celda-dia usando clima rezagado; no es forecasting.
2. **¿Que significa una etiqueta positiva?** Hubo al menos una deteccion FIRMS
   en esa celda y fecha, tras filtro geografico y deduplicacion.
3. **¿Un negativo prueba que no hubo fuego?** No. Es ausencia de deteccion local
   en un dia con deteccion en algun lugar del departamento; no garantiza
   sobrevuelo de esa celda ni ausencia de fuego.
4. **¿De donde salen los datos?** NASA FIRMS para hotspots y Open-Meteo
   Archive para clima, todo real; el test de modelo tiene 8.784 filas.
5. **¿Cuantas muestras hay y cual es el balance?** 43.344 filas: 2.218
   positivas (5,12 %) y 41.126 negativas, en 144 celdas.
6. **¿Por que Madre de Dios?** Es una unidad administrativa amazonica concreta,
   evita mezclar jurisdicciones/climas y tiene bounding box/poligono definidos
   para el recorte.
7. **¿Que paso con la brecha FIRMS de julio-agosto 2026?** Se consultaron
   NOAA20 SP/NRT, NOAA21 NRT y MODIS SP/NRT. Se obtuvieron detecciones
   combinadas en 40/51 dias; 11 dias no devolvieron detecciones y no se
   rellenaron.
8. **¿Como se evita fuga de datos?** Features solo de clima anterior; split
   cronologico por fechas; tuning y umbral con folds/OOF de train; test no se
   usa para seleccionar.
9. **¿Por que XGBoost si RF tiene mejor F1 de test?** Seleccionamos XGBoost por
   F1 temporal OOF 0,4316. RF obtiene F1 holdout 0,5238 frente a XGBoost
   0,5165, pero usar test para elegir implicaria fuga de seleccion.
10. **¿Que representa el umbral 0,65327?** Punto de decision escogido con
    predicciones OOF de entrenamiento para F1; no es probabilidad calibrada ni
    garantia de seguridad.
11. **¿Cual es el error mas importante del modelo?** En holdout hubo 79 falsos
    negativos y 1.196 falsos positivos. Por ello recall alto (0,8961) convive
    con precision 0,3628; ambos deben interpretarse considerando proxies y
    sensores.
12. **¿Que aporta PR-AUC 0,511?** Resume precision-recall bajo prevalencia
    positiva aproximada de 8,65 % en test; es mas informativa que accuracy en
    este escenario desbalanceado.
13. **¿Como se usa la API?** `/predict` recibe `cell_id`, fecha y exactamente
    13 features; responde score, umbral, clase y modelo. Pydantic rechaza
    extras, faltantes y valores no finitos.
14. **¿Como protegen la clave FIRMS?** Se usa solo desde `.env` local o secret
    `MAP_KEY` de Actions; no se incluye en imagen, logs, docs o Git. Los crudos
    tambien se ignoran/no se publican.
15. **¿Puede usarse en emergencias o que pasa si Render duerme?** No debe
    usarse como alerta. Render Free puede dormir; hacemos reintentos y tenemos
    un plan B local/capturas, pero no hay SLA ni garantia de disponibilidad.
