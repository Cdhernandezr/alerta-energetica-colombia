# Decisiones Técnicas — Alerta Energética Colombia

## 1. DuckDB sobre SQLite
**Contexto**: necesitamos almacenar series de tiempo de 3+ años con
consultas analíticas frecuentes (agregaciones, rolling windows, joins).

**Decisión**: DuckDB (columnar, OLAP) sobre SQLite (row-based, OLTP).

**Razón**: DuckDB está optimizado para el patrón de acceso analítico —
lee solo las columnas necesarias en vez de filas completas. Para
`SELECT AVG(valor_kwh) FROM demanda_sin` sobre millones de filas,
DuckDB es 10-100x más rápido que SQLite.

**Trade-off**: SQLite tiene mejor soporte para escrituras concurrentes
de múltiples procesos. No es un problema aquí porque solo un proceso
escribe a la vez (el pipeline de ingesta).

---

## 2. GitHub Actions sobre Apache Airflow
**Contexto**: necesitamos ejecutar el pipeline de ingesta cada 6 horas.

**Decisión**: GitHub Actions con cron schedule.

**Razón**: Airflow requiere scheduler + webserver + metadata DB —
infraestructura que no aporta valor para 6 llamadas de API cada 6 horas.
GitHub Actions es gratuito, el archivo de configuración vive en el mismo
repo que el código, y tiene logs, reintentos y notificaciones de fallo
sin configuración adicional.

**Trade-off**: GitHub Actions tiene límite de 2,000 minutos/mes en el
plan gratuito. Para este proyecto (ejecuciones de ~2 min cada 6h =
~240 min/mes) no es un problema.

---

## 3. pandas < 3.0 fijado en dependencias
**Contexto**: pydataxm 0.3.17 usa `pd.date_range(freq='M')` internamente.

**Problema**: pandas 3.x eliminó el alias `'M'` (reemplazado por `'ME'`).
Esto rompe pydataxm con `ValueError: Invalid frequency: M`.

**Decisión**: fijar `pandas<3.0.0` en pyproject.toml hasta que
pydataxm actualice su código.

**Cómo detectarlo**: `inspect.getsource(ReadDB.request_data)` mostró
el uso interno de `freq='M'`.

---

## 4. Parámetros invertidos en pydataxm
**Contexto**: la documentación oficial de pydataxm dice que `coleccion`
recibe el nombre de la colección y `metrica` recibe el MetricId.

**Realidad**: inspeccionando el código fuente con `inspect.getsource`,
encontramos que:
- `coleccion` recibe el MetricId (ej: 'DemaSIN')
- `metrica` recibe el Entity (ej: 'Sistema', 'Embalse', 'Rio')

**Lección**: ante APIs con comportamiento inesperado, inspeccionar el
código fuente directamente es más confiable que la documentación.

---

## 5. INSERT OR REPLACE para idempotencia
**Contexto**: el pipeline de ingesta puede correr múltiples veces
sobre el mismo rango de fechas.

**Decisión**: usar `INSERT OR REPLACE` en DuckDB en vez de
`INSERT` simple.

**Razón**: garantiza que el pipeline sea idempotente — el resultado
es siempre el mismo sin importar cuántas veces se ejecute. Evita
duplicados sin necesidad de verificar primero si el registro existe.

---

## 6. Formato ancho → largo para precio de bolsa
**Contexto**: PrecBolsNaci llega de la API con 24 columnas de hora
(Values_Hour01 a Values_Hour24) — formato ancho.

**Decisión**: normalizar a formato largo (una fila por hora) con
`pd.melt()` antes de guardar en DuckDB.

**Razón**: el formato largo es más flexible para consultas SQL
(GROUP BY hora, filtros por hora específica) y consistente con
el resto de las tablas.

---

## 7. Anomalía detectada: rezago de datos en la API
**Observación**: los días más recientes (T-1, T-2) a veces muestran
valores anómalos — demanda de 0.45 TWh cuando el promedio es 250 TWh.

**Causa probable**: la API publica datos con rezago de 1-2 días.
Los datos del día anterior pueden estar incompletos al momento
de la descarga.

**Mitigación**: en el pipeline de ingesta, usar `date.today() -
timedelta(days=2)` como fecha fin para evitar datos incompletos.
El script de validación de calidad debe detectar valores fuera
del rango físicamente posible (< 100 TWh/día para DemaSIN).


## 8. Anomalías de precio son eventos reales, no errores

**Observación**: el script de validación detectó 306 horas con
z-score > 4 en precio_bolsa.

**Investigación**: las horas anómalas se concentran en oct-nov 2024,
con precios de hasta 2,675 COP/kWh (z-score 5.92). El precio promedio
de 2024 fue 676 COP/kWh vs 240 COP/kWh en 2025.

**Conclusión**: son precios reales durante el pico de El Niño 2023-2024,
cuando los embalses cayeron a niveles críticos y se activó generación
térmica de emergencia.

**Decisión**: NO eliminar estos registros. Son los eventos de mayor
valor predictivo para el modelo — representan exactamente las crisis
que el sistema de alerta debe anticipar.

**Implicación para el modelo**: usar métricas robustas (MAE en vez de
MSE) porque MSE penaliza desproporcionadamente estos picos extremos,
lo que puede sesgar el modelo hacia minimizar el error en condiciones
normales a costa de fallar en las crisis.

## 9. Porcentaje de embalse puede superar 100%

**Observación**: 30 registros con porcentaje > 1.0, principalmente
embalse PRADO (hasta 1.22) y PLAYAS.

**Causa**: los embalses reportan volumen útil incluyendo vertimientos
— agua que entra en exceso sobre la capacidad nominal y rebosa.
La API de XM reporta este exceso como porcentaje > 100%.

**Decisión**: ajustar rango máximo válido a 1.20. Los 30 registros
restantes con valores > 1.20 (PLAYAS llegó a 1.22) se investigan
caso por caso en el EDA.

**Implicación para el modelo**: no truncar estos valores a 1.0 porque
perderíamos información real sobre el estado hídrico del sistema.