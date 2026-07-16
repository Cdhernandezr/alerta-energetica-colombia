"""
Validación de calidad de datos para el pipeline de ingesta.

Detecta automáticamente:
- Gaps en series de tiempo (fechas faltantes)
- Valores fuera de rango físicamente posible
- Valores anómalos estadísticamente (z-score)
- Datos con rezago (días recientes incompletos)

Decisión de diseño: las validaciones retornan DataFrames con los
problemas encontrados, no lanzan excepciones. Así el pipeline
puede continuar y el analista decide qué hacer con cada problema.
"""

import duckdb
import pandas as pd
from pathlib import Path
from datetime import date, timedelta


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "processed" / "energia_colombia.duckdb"


def get_db_connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH))


# ── Rangos físicamente posibles ───────────────────────────────────────────────
# Basados en conocimiento del dominio del SIN colombiano
RANGOS_VALIDOS = {
    "demanda_sin": {
        "columna": "valor_kwh",
        "min": 150_000_000,   # 150 GWh — mínimo histórico en festivos
        "max": 350_000_000,   # 350 GWh — máximo histórico
    },
    "precio_bolsa": {
        "columna": "valor_cop_kwh",
        "min": 50,            # COP/kWh — precio mínimo posible
        "max": 3_000,         # COP/kWh — precio máximo (crisis El Niño)
    },
    "porcentaje_embalse": {
        "columna": "porcentaje",
        "min": 0.0,           # 0% — embalse vacío
        "max": 1.2,           # Embalses pueden superar 100% por vertimientos
    },
}


def verificar_gaps_temporales(tabla: str, columna_fecha: str = "fecha") -> pd.DataFrame:
    """
    Detecta fechas faltantes en una serie de tiempo.
    Retorna un DataFrame con las fechas que faltan.
    """
    con = get_db_connection()

    df = con.execute(f"""
        SELECT DISTINCT {columna_fecha} AS fecha
        FROM {tabla}
        ORDER BY fecha
    """).df()

    con.close()

    if df.empty:
        return pd.DataFrame(columns=["fecha_faltante"])

    fechas_existentes = set(pd.to_datetime(df["fecha"]).dt.date)
    fecha_min = min(fechas_existentes)
    fecha_max = max(fechas_existentes)

    # Generar rango completo de fechas esperadas
    rango_completo = set()
    cursor = fecha_min
    while cursor <= fecha_max:
        rango_completo.add(cursor)
        cursor += timedelta(days=1)

    fechas_faltantes = sorted(rango_completo - fechas_existentes)

    if fechas_faltantes:
        return pd.DataFrame({"fecha_faltante": fechas_faltantes})
    return pd.DataFrame(columns=["fecha_faltante"])


def verificar_rangos_fisicos(tabla: str) -> pd.DataFrame:
    """
    Detecta valores fuera del rango físicamente posible.
    Retorna filas con valores anómalos.
    """
    if tabla not in RANGOS_VALIDOS:
        return pd.DataFrame()

    config = RANGOS_VALIDOS[tabla]
    columna = config["columna"]
    vmin = config["min"]
    vmax = config["max"]

    con = get_db_connection()

    df = con.execute(f"""
        SELECT *
        FROM {tabla}
        WHERE {columna} < {vmin}
           OR {columna} > {vmax}
        ORDER BY fecha
    """).df()

    con.close()
    return df


def verificar_anomalias_estadisticas(
    tabla: str,
    columna_valor: str,
    umbral_zscore: float = 4.0,
) -> pd.DataFrame:
    """
    Detecta valores estadísticamente anómalos usando z-score.
    Un z-score > 4 significa que el valor está a más de 4
    desviaciones estándar de la media — extremadamente inusual.

    Usamos 4 (no el estándar de 3) porque en series de tiempo
    energéticas hay variaciones estacionales legítimas grandes.
    """
    con = get_db_connection()

    df = con.execute(f"""
        SELECT *,
               (({columna_valor} - AVG({columna_valor}) OVER ())
                / NULLIF(STDDEV({columna_valor}) OVER (), 0)) AS zscore
        FROM {tabla}
        ORDER BY fecha
    """).df()

    con.close()

    anomalias = df[df["zscore"].abs() > umbral_zscore].copy()
    return anomalias


def verificar_datos_recientes(dias_rezago: int = 3) -> pd.DataFrame:
    """
    Verifica si los datos más recientes tienen valores anómalos
    producto del rezago de publicación de la API.
    Retorna un resumen del estado de los últimos N días.
    """
    con = get_db_connection()
    fecha_corte = date.today() - timedelta(days=dias_rezago)

    resultados = []

    # Verificar demanda en días recientes
    df = con.execute(f"""
        SELECT fecha,
               valor_kwh,
               valor_kwh < 150000000 AS posible_incompleto
        FROM demanda_sin
        WHERE fecha >= '{fecha_corte}'
        ORDER BY fecha
    """).df()

    for _, row in df.iterrows():
        resultados.append({
            "tabla": "demanda_sin",
            "fecha": row["fecha"],
            "valor": row["valor_kwh"],
            "posible_incompleto": bool(row["posible_incompleto"]),
        })

    con.close()

    return pd.DataFrame(resultados)


def reporte_completo() -> dict:
    """
    Corre todas las validaciones y retorna un resumen ejecutivo.
    Este es el punto de entrada principal para el monitoreo diario.
    """
    print("🔍 Validación de calidad de datos\n")
    resultados = {}

    tablas_principales = [
        ("demanda_sin", "valor_kwh"),
        ("precio_bolsa", "valor_cop_kwh"),
        ("porcentaje_embalse", "porcentaje"),
    ]

    for tabla, columna in tablas_principales:
        print(f"{'─'*50}")
        print(f"Tabla: {tabla}")

        # Gaps temporales
        gaps = verificar_gaps_temporales(tabla)
        if gaps.empty:
            print("  ✅ Sin gaps temporales")
        else:
            print(f"  ⚠️  {len(gaps)} fechas faltantes")
            print(f"     Primeras 5: {gaps['fecha_faltante'].head().tolist()}")

        # Rangos físicos
        fuera_rango = verificar_rangos_fisicos(tabla)
        if fuera_rango.empty:
            print("  ✅ Todos los valores en rango físico válido")
        else:
            print(f"  ⚠️  {len(fuera_rango)} valores fuera de rango")
            print(f"     {fuera_rango.head(3).to_string()}")

        # Anomalías estadísticas
        anomalias = verificar_anomalias_estadisticas(tabla, columna)
        if anomalias.empty:
            print("  ✅ Sin anomalías estadísticas (z-score > 4)")
        else:
            print(f"  ⚠️  {len(anomalias)} anomalías estadísticas")

        resultados[tabla] = {
            "gaps": len(gaps),
            "fuera_rango": len(fuera_rango),
            "anomalias": len(anomalias),
        }

    # Datos recientes
    print(f"\n{'─'*50}")
    print("Datos recientes (posible rezago de API):")
    recientes = verificar_datos_recientes()
    if not recientes.empty:
        print(recientes.to_string(index=False))

    return resultados


if __name__ == "__main__":
    reporte = reporte_completo()
    print(f"\n{'═'*50}")
    print("📋 Resumen ejecutivo:")
    for tabla, stats in reporte.items():
        estado = "✅" if all(v == 0 for v in stats.values()) else "⚠️"
        print(f"  {estado} {tabla}: gaps={stats['gaps']}, "
              f"fuera_rango={stats['fuera_rango']}, "
              f"anomalias={stats['anomalias']}")