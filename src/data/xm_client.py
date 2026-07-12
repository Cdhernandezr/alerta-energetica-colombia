"""
Cliente para la API de XM (Sistema Interconectado Nacional de Colombia).

Aprendizajes de la inspección real de la API (pydataxm 0.3.17):
- coleccion = MetricId  (ej: 'DemaSIN')
- metrica   = Entity    (ej: 'Sistema', 'Embalse', 'Rio')
- La API divide internamente por meses — no necesitamos chunks manuales
- PrecBolsNaci viene en formato ancho (24 columnas hora) — requiere melt
- Resto de métricas vienen en formato largo estándar (Id, Name, Value, Date)
- pandas>=3.0 rompe pydataxm (freq='M' eliminado) — usar pandas 2.x
"""

import duckdb
import pandas as pd
from pydataxm.pydataxm import ReadDB
from datetime import date, timedelta
from pathlib import Path


# ── Rutas ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "processed" / "energia_colombia.duckdb"

# ── Métricas confirmadas con la API real ──────────────────────────────────────
# Formato: (metrica_id, entidad, tabla_destino, tipo_formato)
# tipo_formato: 'largo' = (Id, Name, Value, Date)
#               'horario' = (Id, Values_Hour01..24, Date) — requiere melt
METRICAS = [
    ("DemaSIN",          "Sistema", "demanda_sin",        "largo"),
    ("PrecBolsNaci",     "Sistema", "precio_bolsa",       "horario"),
    ("VoluUtilDiarEner", "Embalse", "volumen_util",       "largo"),
    ("PorcVoluUtilDiar", "Embalse", "porcentaje_embalse", "largo"),
    ("AporEner",         "Rio",     "aportes_energia",    "largo"),
    ("AporCaudal",       "Rio",     "aportes_caudal",     "largo"),
]


def get_db_connection() -> duckdb.DuckDBPyConnection:
    """Retorna conexión a DuckDB. Crea el directorio si no existe."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DB_PATH))


def inicializar_tablas():
    """Crea todas las tablas si no existen."""
    con = get_db_connection()

    # Demanda diaria del SIN (un valor por día)
    con.execute("""
        CREATE TABLE IF NOT EXISTS demanda_sin (
            fecha       DATE NOT NULL,
            valor_kwh   DOUBLE,
            fecha_carga TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (fecha)
        )
    """)

    # Precio de bolsa horario (24 valores por día)
    con.execute("""
        CREATE TABLE IF NOT EXISTS precio_bolsa (
            fecha        DATE NOT NULL,
            hora         INTEGER NOT NULL,  -- 1 a 24
            valor_cop_kwh DOUBLE,
            fecha_carga  TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (fecha, hora)
        )
    """)

    # Volumen útil por embalse (kWh)
    con.execute("""
        CREATE TABLE IF NOT EXISTS volumen_util (
            fecha       DATE NOT NULL,
            embalse     VARCHAR NOT NULL,
            valor_kwh   DOUBLE,
            fecha_carga TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (fecha, embalse)
        )
    """)

    # Porcentaje de llenado por embalse (0 a 1)
    con.execute("""
        CREATE TABLE IF NOT EXISTS porcentaje_embalse (
            fecha        DATE NOT NULL,
            embalse      VARCHAR NOT NULL,
            porcentaje   DOUBLE,  -- valor entre 0 y 1
            fecha_carga  TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (fecha, embalse)
        )
    """)

    # Aportes hídricos por río (kWh equivalente)
    con.execute("""
        CREATE TABLE IF NOT EXISTS aportes_energia (
            fecha       DATE NOT NULL,
            rio         VARCHAR NOT NULL,
            valor_kwh   DOUBLE,
            fecha_carga TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (fecha, rio)
        )
    """)

    # Caudal por río (m3/s)
    con.execute("""
        CREATE TABLE IF NOT EXISTS aportes_caudal (
            fecha       DATE NOT NULL,
            rio         VARCHAR NOT NULL,
            valor_m3s   DOUBLE,
            fecha_carga TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (fecha, rio)
        )
    """)

    con.close()
    print("✅ Tablas inicializadas en DuckDB")


def normalizar_largo(df: pd.DataFrame, tabla: str) -> pd.DataFrame:
    """
    Normaliza el formato largo estándar (Id, Name, Value, Date)
    al esquema de cada tabla destino.
    """
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.date

    if tabla == "demanda_sin":
        return df[["Date", "Value"]].rename(columns={
            "Date": "fecha",
            "Value": "valor_kwh",
        })

    elif tabla in ("volumen_util",):
        return df[["Date", "Name", "Value"]].rename(columns={
            "Date": "fecha",
            "Name": "embalse",
            "Value": "valor_kwh",
        })

    elif tabla == "porcentaje_embalse":
        return df[["Date", "Name", "Value"]].rename(columns={
            "Date": "fecha",
            "Name": "embalse",
            "Value": "porcentaje",
        })

    elif tabla == "aportes_energia":
        return df[["Date", "Name", "Value"]].rename(columns={
            "Date": "fecha",
            "Name": "rio",
            "Value": "valor_kwh",
        })

    elif tabla == "aportes_caudal":
        return df[["Date", "Name", "Value"]].rename(columns={
            "Date": "fecha",
            "Name": "rio",
            "Value": "valor_m3s",
        })

    return df


def normalizar_horario(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte el formato ancho de precio (24 columnas hora)
    a formato largo (una fila por hora).

    Entrada:  columnas Id, Values_Hour01..Hour24, Date
    Salida:   columnas fecha, hora (1-24), valor_cop_kwh
    """
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.date

    hora_cols = [c for c in df.columns if c.startswith("Values_Hour")]

    df_largo = df.melt(
        id_vars=["Date"],
        value_vars=hora_cols,
        var_name="hora_str",
        value_name="valor_cop_kwh",
    )

    # Extraer número de hora: "Values_Hour01" → 1
    df_largo["hora"] = df_largo["hora_str"].str.extract(r"(\d+)$").astype(int)

    return df_largo[["Date", "hora", "valor_cop_kwh"]].rename(
        columns={"Date": "fecha"}
    )


def descargar_metrica(
    metrica_id: str,
    entidad: str,
    fecha_inicio: date,
    fecha_fin: date,
) -> pd.DataFrame:
    """
    Descarga una métrica de XM para un rango de fechas.
    La API maneja internamente la división por meses.
    """
    api = ReadDB()

    print(f"  [{metrica_id}/{entidad}] {fecha_inicio} → {fecha_fin}")

    try:
        df = api.request_data(
            coleccion=metrica_id,
            metrica=entidad,
            start_date=fecha_inicio.strftime("%Y-%m-%d"),
            end_date=fecha_fin.strftime("%Y-%m-%d"),
        )

        if df is None or df.empty:
            print("  ⚠️  Sin datos")
            return pd.DataFrame()

        return df

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return pd.DataFrame()


def guardar_en_duckdb(df_normalizado: pd.DataFrame, tabla: str):
    """
    Inserta datos en DuckDB usando INSERT OR REPLACE
    para manejar duplicados sin error.
    """
    if df_normalizado.empty:
        return

    con = get_db_connection()

    # Registrar el dataframe como tabla temporal
    con.register("df_temp", df_normalizado)

    # INSERT OR REPLACE según la tabla
    if tabla == "demanda_sin":
        con.execute("""
            INSERT OR REPLACE INTO demanda_sin (fecha, valor_kwh)
            SELECT fecha, valor_kwh FROM df_temp
        """)

    elif tabla == "precio_bolsa":
        con.execute("""
            INSERT OR REPLACE INTO precio_bolsa (fecha, hora, valor_cop_kwh)
            SELECT fecha, hora, valor_cop_kwh FROM df_temp
        """)

    elif tabla == "volumen_util":
        con.execute("""
            INSERT OR REPLACE INTO volumen_util (fecha, embalse, valor_kwh)
            SELECT fecha, embalse, valor_kwh FROM df_temp
        """)

    elif tabla == "porcentaje_embalse":
        con.execute("""
            INSERT OR REPLACE INTO porcentaje_embalse
                (fecha, embalse, porcentaje)
            SELECT fecha, embalse, porcentaje FROM df_temp
        """)

    elif tabla == "aportes_energia":
        con.execute("""
            INSERT OR REPLACE INTO aportes_energia (fecha, rio, valor_kwh)
            SELECT fecha, rio, valor_kwh FROM df_temp
        """)

    elif tabla == "aportes_caudal":
        con.execute("""
            INSERT OR REPLACE INTO aportes_caudal (fecha, rio, valor_m3s)
            SELECT fecha, rio, valor_m3s FROM df_temp
        """)

    filas = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    con.close()
    print(f"  💾 {tabla}: {len(df_normalizado)} filas insertadas "
          f"(total en DB: {filas})")


def descargar_y_guardar(
    metrica_id: str,
    entidad: str,
    tabla: str,
    tipo: str,
    fecha_inicio: date,
    fecha_fin: date,
):
    """Pipeline completo: descarga → normaliza → guarda en DuckDB."""
    df_crudo = descargar_metrica(metrica_id, entidad, fecha_inicio, fecha_fin)

    if df_crudo.empty:
        return

    if tipo == "horario":
        df_norm = normalizar_horario(df_crudo)
    else:
        df_norm = normalizar_largo(df_crudo, tabla)

    guardar_en_duckdb(df_norm, tabla)


def consultar_resumen():
    """Muestra cuántos registros hay en cada tabla. Útil para verificar."""
    con = get_db_connection()
    tablas = [
        "demanda_sin", "precio_bolsa", "volumen_util",
        "porcentaje_embalse", "aportes_energia", "aportes_caudal",
    ]
    print("\n📊 Estado actual de la base de datos:")
    for tabla in tablas:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
            print(f"  {tabla:<25} {n:>8} registros")
        except Exception:
            print(f"  {tabla:<25} tabla no existe aún")
    con.close()


if __name__ == "__main__":
    print("🚀 Pipeline de ingesta XM — prueba con últimos 7 días\n")

    inicializar_tablas()

    fecha_fin = date.today() - timedelta(days=1)
    fecha_inicio = fecha_fin - timedelta(days=6)

    print(f"Rango: {fecha_inicio} → {fecha_fin}\n")

    for metrica_id, entidad, tabla, tipo in METRICAS:
        print(f"\n{'─'*50}")
        descargar_y_guardar(
            metrica_id, entidad, tabla, tipo,
            fecha_inicio, fecha_fin,
        )

    consultar_resumen()