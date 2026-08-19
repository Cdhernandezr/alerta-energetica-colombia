"""
Cliente para la API de Open-Meteo.
https://open-meteo.com

Decisiones técnicas:
- HTTP en vez de HTTPS en desarrollo local (WSL bloquea SSL saliente)
- En produccion (Streamlit Cloud) usar HTTPS sin cambios
- Endpoint /archive para historico, /forecast para pronostico 16 dias
- Datos diarios pre-agregados, sin necesidad de agregacion adicional
- Sin autenticacion, hasta 10,000 llamadas gratuitas por dia

Embalses cubiertos:
- El Quimbo (Huila):       2.0797, -75.7625
- Guavio (Cundinamarca):   4.6833, -73.5500
- Porce III (Antioquia):   7.1167, -75.0833
- Ituango (Antioquia):     7.2167, -75.6667
- Urra (Cordoba):          7.8833, -76.1000
- Betania (Huila):         2.6333, -75.4167
"""

import datetime as dt
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import requests

# ── Rutas ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "processed" / "energia_colombia.duckdb"

# ── URLs ──────────────────────────────────────────────────────────────────────
BASE_ARCHIVE = "http://archive-api.open-meteo.com/v1/archive"
BASE_FORECAST = "http://api.open-meteo.com/v1/forecast"

# ── Variables climaticas ──────────────────────────────────────────────────────
VARIABLES_DIARIAS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
]

# ── Embalses criticos con coordenadas ─────────────────────────────────────────
EMBALSES = {
    "EL_QUIMBO": {"lat": 2.0797, "lon": -75.7625, "depto": "Huila"},
    "GUAVIO": {"lat": 4.6833, "lon": -73.5500, "depto": "Cundinamarca"},
    "PORCE_III": {"lat": 7.1167, "lon": -75.0833, "depto": "Antioquia"},
    "ITUANGO": {"lat": 7.2167, "lon": -75.6667, "depto": "Antioquia"},
    "URRA": {"lat": 7.8833, "lon": -76.1000, "depto": "Cordoba"},
    "BETANIA": {"lat": 2.6333, "lon": -75.4167, "depto": "Huila"},
}


def get_db_connection() -> duckdb.DuckDBPyConnection:
    """Retorna conexion a DuckDB. Crea el directorio si no existe."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DB_PATH))


def inicializar_tablas() -> None:
    """Crea las tablas de clima si no existen."""
    con = get_db_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS clima_historico (
            fecha         DATE NOT NULL,
            embalse       VARCHAR NOT NULL,
            temp_max      DOUBLE,
            temp_min      DOUBLE,
            temp_mean     DOUBLE,
            precipitacion DOUBLE,
            fecha_carga   TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (fecha, embalse)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS clima_pronostico (
            fecha         DATE NOT NULL,
            embalse       VARCHAR NOT NULL,
            temp_max      DOUBLE,
            temp_min      DOUBLE,
            temp_mean     DOUBLE,
            precipitacion DOUBLE,
            fecha_carga   TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (fecha, embalse)
        )
    """)
    con.close()
    print("Tablas de clima inicializadas")


def _normalizar_df(df: pd.DataFrame, embalse: str) -> pd.DataFrame:
    """
    Normaliza el dataframe crudo de Open-Meteo al esquema de DuckDB.
    Extrae esta logica para no repetirla en historico y pronostico.
    """
    df = df.copy()
    df["embalse"] = embalse
    df = df.rename(columns={
        "time": "fecha",
        "temperature_2m_max": "temp_max",
        "temperature_2m_min": "temp_min",
        "temperature_2m_mean": "temp_mean",
        "precipitation_sum": "precipitacion",
    })
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    return df


def descargar_historico_embalse(
    embalse: str,
    lat: float,
    lon: float,
    fecha_inicio: date,
    fecha_fin: date,
) -> pd.DataFrame:
    """
    Descarga datos historicos de clima para un embalse.
    Usa el endpoint /archive de Open-Meteo.
    Open-Meteo no tiene limite de dias por llamada en archive,
    se puede pedir 3 anos en una sola llamada.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": fecha_inicio.strftime("%Y-%m-%d"),
        "end_date": fecha_fin.strftime("%Y-%m-%d"),
        "daily": VARIABLES_DIARIAS,
        "timezone": "America/Bogota",
    }
    try:
        resp = requests.get(BASE_ARCHIVE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return _normalizar_df(pd.DataFrame(data["daily"]), embalse)
    except requests.exceptions.Timeout:
        print(f"  Timeout {embalse}: la API no respondio en 30s")
        return pd.DataFrame()
    except requests.exceptions.ConnectionError:
        print(f"  Error de conexion {embalse}: verifica la red")
        return pd.DataFrame()
    except requests.exceptions.HTTPError as e:
        print(f"  Error HTTP {embalse}: {e}")
        return pd.DataFrame()
    except (KeyError, ValueError) as e:
        print(f"  Error procesando respuesta {embalse}: {e}")
        return pd.DataFrame()


def descargar_pronostico_embalse(
    embalse: str,
    lat: float,
    lon: float,
    dias: int = 16,
) -> pd.DataFrame:
    """
    Descarga pronostico de hasta 16 dias para un embalse.
    Usa el endpoint /forecast de Open-Meteo.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": VARIABLES_DIARIAS,
        "timezone": "America/Bogota",
        "forecast_days": dias,
    }
    try:
        resp = requests.get(BASE_FORECAST, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return _normalizar_df(pd.DataFrame(data["daily"]), embalse)
    except requests.exceptions.Timeout:
        print(f"  Timeout pronostico {embalse}: la API no respondio en 30s")
        return pd.DataFrame()
    except requests.exceptions.ConnectionError:
        print(f"  Error de conexion pronostico {embalse}: verifica la red")
        return pd.DataFrame()
    except requests.exceptions.HTTPError as e:
        print(f"  Error HTTP pronostico {embalse}: {e}")
        return pd.DataFrame()
    except (KeyError, ValueError) as e:
        print(f"  Error procesando pronostico {embalse}: {e}")
        return pd.DataFrame()


def guardar_en_duckdb(df: pd.DataFrame, tabla: str) -> None:
    """Guarda datos climaticos en DuckDB con INSERT OR REPLACE."""
    if df.empty:
        return
    con = get_db_connection()
    con.register("df_temp", df)
    con.execute(f"""
        INSERT OR REPLACE INTO {tabla}
            (fecha, embalse, temp_max, temp_min, temp_mean, precipitacion)
        SELECT fecha, embalse, temp_max, temp_min, temp_mean, precipitacion
        FROM df_temp
    """)
    n = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    con.close()
    print(f"  {tabla}: {len(df)} filas insertadas (total: {n})")


def descargar_historico_completo(
    fecha_inicio: date,
    fecha_fin: date,
) -> None:
    """Descarga historico climatico para todos los embalses."""
    print(f"\nHistorico climatico: {fecha_inicio} a {fecha_fin}")
    print(f"   {len(EMBALSES)} embalses\n")
    for embalse, coords in EMBALSES.items():
        print(f"  [{embalse}] {coords['depto']}")
        df = descargar_historico_embalse(
            embalse, coords["lat"], coords["lon"],
            fecha_inicio, fecha_fin,
        )
        if not df.empty:
            guardar_en_duckdb(df, "clima_historico")
    print("\nHistorico climatico completo")


def descargar_pronostico_completo(dias: int = 16) -> None:
    """Descarga pronostico para todos los embalses."""
    print(f"\nPronostico {dias} dias para {len(EMBALSES)} embalses\n")
    for embalse, coords in EMBALSES.items():
        print(f"  [{embalse}]")
        df = descargar_pronostico_embalse(
            embalse, coords["lat"], coords["lon"], dias,
        )
        if not df.empty:
            guardar_en_duckdb(df, "clima_pronostico")
    print("\nPronostico actualizado")


def verificar_cobertura() -> None:
    """Muestra cobertura de fechas en las tablas de clima."""
    con = get_db_connection()
    print("\nCobertura de datos climaticos:")
    print(f"  {'Tabla':<25} {'Desde':<12} {'Hasta':<12} {'Registros':>10}")
    print(f"  {'─'*25} {'─'*12} {'─'*12} {'─'*10}")
    for tabla in ["clima_historico", "clima_pronostico"]:
        try:
            row = con.execute(f"""
                SELECT
                    MIN(fecha)::VARCHAR AS desde,
                    MAX(fecha)::VARCHAR AS hasta,
                    COUNT(*)           AS registros
                FROM {tabla}
            """).fetchone()
            if row and row[0] is not None:
                print(f"  {tabla:<25} {row[0]:<12} {row[1]:<12} {row[2]:>10}")
            else:
                print(f"  {tabla:<25} sin datos")
        except duckdb.Error:
            print(f"  {tabla:<25} sin datos")
    print("\nEmbalses con datos:")
    try:
        df = con.execute("""
            SELECT
                embalse,
                MAX(fecha)::VARCHAR          AS ultima_fecha,
                ROUND(AVG(temp_mean), 1)     AS temp_promedio,
                ROUND(SUM(precipitacion), 1) AS precip_total
            FROM clima_historico
            GROUP BY embalse
            ORDER BY embalse
        """).df()
        print(df.to_string(index=False))
    except duckdb.Error as e:
        print(f"  Error: {e}")
    con.close()


if __name__ == "__main__":
    inicializar_tablas()

    if len(sys.argv) == 1:
        print("Modo prueba: ultimos 30 dias + pronostico 16 dias\n")
        fecha_fin = dt.datetime.now(tz=dt.UTC).date() - timedelta(days=1)
        fecha_inicio = fecha_fin - timedelta(days=29)
        descargar_historico_completo(fecha_inicio, fecha_fin)
        descargar_pronostico_completo()
        verificar_cobertura()

    elif sys.argv[1] == "historico":
        fecha_inicio = date(2023, 1, 1)
        fecha_fin = dt.datetime.now(tz=dt.UTC).date() - timedelta(days=1)
        descargar_historico_completo(fecha_inicio, fecha_fin)
        verificar_cobertura()

    elif sys.argv[1] == "pronostico":
        descargar_pronostico_completo()
        verificar_cobertura()

    elif sys.argv[1] == "cobertura":
        verificar_cobertura()