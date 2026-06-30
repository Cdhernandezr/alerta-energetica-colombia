# Alerta Energética Colombia 🇨🇴⚡

Sistema de alerta temprana que predice estrés en el sistema eléctrico colombiano
correlacionando datos climáticos, hidrológicos y de demanda en tiempo real,
con foco en el impacto del Fenómeno de El Niño 2026.

## Estado del proyecto
🚧 En construcción — Semana 1/8: ingesta de datos

## Stack tecnológico
- **Datos**: pydataxm (XM), sodapy (IDEAM), Open-Meteo API
- **Almacenamiento**: DuckDB (analítico, columnar)
- **ML**: XGBoost, scikit-learn
- **Dashboard**: Streamlit + Plotly + Folium
- **Orquestación**: GitHub Actions
- **Entorno**: Python 3.11, uv

## Estructura
\`\`\`
alerta-energetica-colombia/
├── src/          # Código fuente modular
├── notebooks/    # EDA y experimentos
├── dashboard/    # App Streamlit
├── data/         # Datos (no versionados)
├── models/       # Modelos entrenados (no versionados)
├── tests/        # Tests unitarios
└── docs/         # Documentación técnica
\`\`\`

## Cómo correr el proyecto
\`\`\`bash
# Clonar e instalar dependencias
git clone https://github.com/TU_USUARIO/alerta-energetica-colombia.git
cd alerta-energetica-colombia
uv sync

# Descargar datos históricos
uv run python src/data/xm_client.py

# Correr dashboard
uv run streamlit run dashboard/app.py
\`\`\`

## Documentación técnica
- [Arquitectura del sistema](docs/arquitectura.md)
- [Decisiones técnicas justificadas](docs/decisiones_tecnicas.md)
