# Puno: datos usados y experimento de mejora

Auditoría y comparación ejecutadas el 21 de octubre de 2026. El modelo servido
por la API se conserva; el experimento genera un candidato separado.

## ¿Se entrena con toda la data?

**No con toda la descarga actual del mapa.** Sí se asignan todas las filas
válidas del CSV de entrenamiento a desarrollo o prueba, sin recortar el CSV a
una muestra de puntos del mapa.

| Conjunto | Registros de celda y día | Fechas |
| --- | ---: | --- |
| CSV procesado | 350.192 | 09/11/2024–10/10/2026 |
| Desarrollo: ajuste y validación | 279.950 | 09/11/2024–21/05/2026 |
| Prueba temporal reservada | 70.242 | 22/05/2026–10/10/2026 |
| Puno: desarrollo | 15.400; 372 positivos | Antes de la prueba |
| Puno: prueba | 3.864; 533 positivos | 22/05/2026–10/10/2026 |

Los 533 positivos no son 533 incendios independientes: indican celdas y días
con al menos una detección. Puno tiene 28 celdas representadas por su centro.

Las detecciones originales se agregan a una malla de 0,5°. Se necesitan 30 días
previos de meteorología para crear las variables, por lo que se excluye el
período inicial sin historia suficiente. También se excluyen días sin actividad
FIRMS en toda el área; los ceros restantes son un proxy de no detección, no
confirmación de ausencia de incendio. El CSV contiene 120.378 detecciones
agregadas en sus filas retenidas. Contar puntos del mapa y contar filas de
entrenamiento son operaciones distintas.

La descarga actual contiene 148.067 observaciones dentro de Perú hasta el
21/10/2026. **14.174** son posteriores al final del dataset, **749** de ellas en
Puno. Al comparar las coordenadas con la misma malla, otros **176** registros
antes considerados negativos ahora contienen detecciones en el archivo
actualizado; **9** son de Puno. Esta diferencia refleja la ampliación de fuentes
que llegó al mapa, sin reconstruir todavía las etiquetas del entrenamiento.
Los hashes y conteos están en `reports/training_data_audit.json`.

## Por qué Puno necesita atención

- En desarrollo, solo el **2,42 %** de los registros de Puno era positivo;
  en prueba, el **13,79 %**. Las distribuciones no son iguales.
- Los positivos de desarrollo provienen de `VIIRS_SNPP_SP`. La prueba mezcla
  SNPP, NOAA20, NOAA21 y MODIS, porque el flujo original agregaba otros sensores
  durante un intervalo de respaldo. La época del año también cambia. Estos
  datos muestran un cambio de distribución, pero no aíslan una causa única.
- El modelo nacional usa 25 series climáticas representativas. Cada celda
  hereda la serie regional con mayor solapamiento; no se resuelven las
  diferencias meteorológicas entre todas las zonas de Puno.
- El umbral nacional optimiza el conjunto del país, no cada región.

## Experimento realizado

Se fijaron tres alternativas antes de medir el resultado de prueba:

1. Conservar las probabilidades del modelo nacional y seleccionar un umbral
   específico de Puno con predicciones temporales fuera de muestra.
2. Regresión logística entrenada solo en Puno.
3. HistGradientBoosting entrenado solo en Puno.

Cada candidato usa tres pliegues temporales crecientes dentro del período de
desarrollo. Se eligió por F1 regional de desarrollo, con average precision como
desempate. Ganó **el umbral regional sobre el modelo nacional**; los modelos
especializados no superaron esa alternativa en desarrollo. Después de fijar
la elección se comparó únicamente el candidato elegido con el modelo actual
sobre la prueba histórica.

| Puno, mismo conjunto de prueba | Actual | Umbral regional experimental |
| --- | ---: | ---: |
| Umbral | 0,1748 | 0,0866 |
| Aciertos con detección | 8 | 249 |
| Detecciones omitidas | 525 | 284 |
| Falsos positivos | 17 | 889 |
| Precisión | 32,0 % | 21,9 % |
| Recall | 1,5 % | 46,7 % |
| F1 | 0,029 | 0,298 |
| Average precision, rotulada PR-AUC en la app | 0,211 | 0,211 |

**Mejora la sensibilidad, no la calidad de las probabilidades.** Cambiar un
umbral no altera el orden de los casos; por eso PR-AUC y Brier permanecen
iguales. El aumento de falsos positivos impide concluir que el candidato sea
mejor para cualquier uso. Por esta razón queda como experimento y no reemplaza
el comportamiento actual de la aplicación.

Esta prueba histórica ya había sido examinada para detectar el problema.
Aunque no se usaron sus etiquetas para ajustar parámetros o umbrales en este
experimento, el resultado es una comparación exploratoria: no una nueva
validación independiente ni evidencia de capacidad de alerta futura.
Los resultados completos, fechas de pliegues, parámetros y hashes están en
`reports/puno_experiment.json`. El candidato local está en
`models/puno_candidate.joblib` y se excluye de Git como los otros experimentos.

Reproducir desde la raíz del proyecto, con el entorno virtual activo:

```bash
python -m src.wildfire.regional_experiment
```

El comando rechaza sobrescribir el modelo, las métricas o el CSV de producción.
El proceso de selección no consulta los resultados de prueba. Cambiar el CSV
exige evaluar otra cohorte, no atribuir la diferencia al mismo experimento.

## Recomendaciones de la auditoría inicial

1. Reconstruir etiquetas con un criterio de sensores consistente a lo largo del
   tiempo. Usar varios sensores solo en el tramo de prueba cambia la definición
   efectiva del objetivo. Verificar disponibilidad antes de llamar completo al
   archivo y mantener la procedencia de cada producto.
2. Incorporar las nuevas detecciones junto con meteorología suficiente para sus
   fechas; actualizar el mapa por sí solo no reentrena el modelo.
3. Probar clima por celda o por zonas homogéneas de Puno. Si se adopta, la API
   debe consultar el mismo tipo de variables que recibió el entrenamiento.
4. Evaluar estacionalidad, elevación y vegetación con variables disponibles en
   el momento de la predicción, y comparar con un modelo sencillo de referencia.
5. Fijar un período futuro de evaluación antes de seleccionar otra versión.
   Comparar sensibilidad, falsos positivos, calibración y rendimiento regional,
   además del F1 nacional. Entrenar con el 100 % y volver a medir en esas mismas
   filas produciría una cifra engañosa.

La API `/model-info` y el panel «Sobre el modelo» ahora muestran cuántos registros
se destinan a ajuste y a prueba y aclaran que actualizar las observaciones no
reentrena. Los próximos entrenamientos guardarán el hash del CSV y las fechas
exactas de ajuste para facilitar esta auditoría.

Referencias metodológicas:
[separación temporal](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
y [ajuste de umbral sin reutilizar los datos de ajuste del clasificador](https://scikit-learn.org/1.6/auto_examples/model_selection/plot_cost_sensitive_learning.html).


## Mejora prioritaria implementada y comprobada

El flujo nacional ahora consulta la disponibilidad oficial y usa **el mismo
satélite VIIRS S-NPP** durante todo el período: SP hasta el 30/06/2026 y NRT desde
el 01/07/2026 en esta ejecución. No añade NOAA20/21 o MODIS solo durante un hueco.
Si los productos de ese satélite no cubren el intervalo solicitado, se detiene
la construcción del candidato. La disponibilidad del producto no garantiza que
cada celda haya tenido un sobrevuelo válido. SP y NRT también pueden tener
diferencias de procesamiento; mantener el satélite reduce una inconsistencia,
no elimina todos los cambios de distribución.

Para las **28 celdas cuyo centro cae en Puno**, se descargó meteorología histórica
por centro de celda, con 731 días por ubicación y sin valores meteorológicos
faltantes. En el resto del país se conserva la asignación regional existente.
Los perfiles exportan la relación celda–ubicación para que mapa, escenarios y
consulta reciente usen la misma ubicación al activar un modelo entrenado así.
Los días meteorológicos se definen en UTC, igual que el entrenamiento.

Se mantuvo el final del dataset en el **10/10/2026** y el inicio de prueba en el
**22/05/2026** para comparar el cambio sin mover el corte temporal. El nuevo CSV
contiene **347.647 filas**: **279.950** para ajuste/validación y **67.697** para
prueba. No es una muestra del mapa: se usan todas las filas válidas, reservando
la prueba fuera del ajuste. El mapa conserva las observaciones multisensor y
más recientes; estas no se convierten automáticamente en etiquetas comparables.

Se entrenaron logística, HistGradientBoosting y XGBoost, con cinco ensayos por
modelo y tres pliegues temporales. La selección y los umbrales se fijaron usando
solo desarrollo; ganó HistGradientBoosting. Para comparar con la versión anterior
se cruzaron fechas y celdas y se usó la etiqueta corregida en ambos modelos.
Cada modelo recibió las variables climáticas correspondientes a su entrenamiento.

| Mismas filas y etiquetas corregidas | Anterior | Candidato |
| --- | ---: | ---: |
| Perú: PR-AUC | 0,418 | 0,434 |
| Perú: F1 | 0,459 | 0,466 |
| Puno: PR-AUC | 0,169 | 0,206 |
| Puno: F1 | 0,032 | 0,027 |
| Puno: verdaderos positivos | 7 | 6 |
| Puno: falsos positivos | 18 | 25 |

Puno aporta 3.668 filas comunes y 408 positivos. No se deben comparar estas cifras
directamente con el antiguo 0,211 / 0,029: cambiaron las etiquetas y las fechas
activas retenidas. La corrección mejora el orden de las probabilidades y el Brier,
pero aún no mejora las decisiones binarias de Puno con el umbral nacional.
**El candidato no se activó**: no superó el criterio fijado de conservar o mejorar
PR-AUC y F1 tanto nacional como regional. No se reajustó el umbral mirando la
prueba. Esta comparación sigue siendo exploratoria, porque el período histórico
ya había sido inspeccionado; hace falta una evaluación futura separada.

Resultados y hashes: `reports/priority_improvement.json`. Candidato, dataset,
perfiles y métricas completos: `data/experiments/consistent_puno/`. Copia de la
versión anterior: `data/experiments/priority_baseline/`. Estos directorios no se
incluyen en Git ni en Docker. Reproducir:

```bash
python -m src.wildfire.priority_experiment --trials 5
# Reutilizar el dataset ya construido:
python -m src.wildfire.priority_experiment --skip-ingest --trials 5
```

El comando no sustituye los artefactos servidos. El flujo automático tampoco
publica perfiles de un candidato rechazado junto con un modelo anterior.
En la interfaz se eliminó el aviso regional sobre el mapa: las métricas están en
**Sobre el modelo → Ver validación del modelo**, cerrado por defecto.

Fuentes para la descarga: [disponibilidad FIRMS](https://firms.modaps.eosdis.nasa.gov/api/data_availability)
y [meteorología histórica Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api).
