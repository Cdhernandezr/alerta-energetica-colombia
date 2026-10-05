"""
Configuracion centralizada del proyecto.

Cualquier valor que se use en mas de un modulo vive aqui.
Cambiar un valor aqui lo propaga automaticamente a todo el proyecto.
"""

from pathlib import Path

# ── Rutas base ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"

# ── Base de datos ─────────────────────────────────────────────────────────────
DB_PATH = DATA_DIR / "processed" / "energia_colombia.duckdb"

# ── APIs ──────────────────────────────────────────────────────────────────────
XM_BASE_ARCHIVE = "http://archive-api.open-meteo.com/v1/archive"
XM_BASE_FORECAST = "http://api.open-meteo.com/v1/forecast"

# ── Parametros del dominio ────────────────────────────────────────────────────
# Basados en conocimiento del sistema electrico colombiano
DEMANDA_MIN_KWH = 150_000_000   # 150 GWh — minimo historico en festivos
DEMANDA_MAX_KWH = 350_000_000   # 350 GWh — maximo historico

PRECIO_MIN_COP = 50             # COP/kWh — precio minimo posible
PRECIO_MAX_COP = 3_000          # COP/kWh — precio maximo (crisis El Nino)

PORCENTAJE_EMBALSE_MIN = 0.0    # 0% — embalse vacio
PORCENTAJE_EMBALSE_MAX = 1.20   # 120% — incluye vertimientos

# Thresholds de clasificacion de riesgo
UMBRAL_CRITICO = 0.35           # < 35% = estado Critico
UMBRAL_ATENCION = 0.50          # 35-50% = estado Atencion
                                # > 50% = estado Normal

# ── Embalses criticos del SIN ─────────────────────────────────────────────────
EMBALSES = {
    "EL_QUIMBO": {"lat": 2.0797, "lon": -75.7625, "depto": "Huila"},
    "GUAVIO": {"lat": 4.6833, "lon": -73.5500, "depto": "Cundinamarca"},
    "PORCE_III": {"lat": 7.1167, "lon": -75.0833, "depto": "Antioquia"},
    "ITUANGO": {"lat": 7.2167, "lon": -75.6667, "depto": "Antioquia"},
    "URRA": {"lat": 7.8833, "lon": -76.1000, "depto": "Cordoba"},
    "BETANIA": {"lat": 2.6333, "lon": -75.4167, "depto": "Huila"},
}

# ── Parametros de ingesta ─────────────────────────────────────────────────────
DIAS_REZAGO_API = 2             # La API de XM publica con 2 dias de retraso
CHUNK_DIAS_XM = 29              # Maximo de dias por llamada a XM