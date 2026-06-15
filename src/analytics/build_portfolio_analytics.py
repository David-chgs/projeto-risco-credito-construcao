"""
build_portfolio_analytics.py

Builds four aggregated analytics tables from processed_empreendimentos
for BI consumption (Metabase / PostgreSQL export layer).

Tables created in DuckDB and mirrored as Parquet
─────────────────────────────────────────────────
analytics_carteira_cenario   — portfolio health by viability scenario
analytics_carteira_regiao    — regional risk concentration + INCC join key
analytics_carteira_padrao    — padrão × cenário risk matrix (credit scorecard input)
analytics_pipeline_mensal    — monthly origination pipeline (volume + margin trend)

Prerequisite: processed_empreendimentos must exist in credit_risk.duckdb.
Run src.processing.process_empreendimentos before this module.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
LOG_DIR = PROJECT_ROOT / "logs"

DUCKDB_PATH = WAREHOUSE_DIR / "credit_risk.duckdb"

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Analytics SQL definitions
# ──────────────────────────────────────────────────────────────────────────────

_SQL_CARTEIRA_CENARIO = """
CREATE OR REPLACE TABLE analytics_carteira_cenario AS
SELECT
    cenario_viabilidade,
    COUNT(*)                                          AS qtd_propostas,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct_carteira,
    ROUND(SUM(vgv)                           / 1e6, 2) AS vgv_total_mm,
    ROUND(AVG(vgv)                           / 1e6, 2) AS vgv_medio_mm,
    ROUND(SUM(custo_construcao)              / 1e6, 2) AS custo_construcao_total_mm,
    ROUND(SUM(valor_financiamento_pretendido)/ 1e6, 2) AS financiamento_total_mm,
    ROUND(AVG(margem_pct_vgv)        * 100,  2) AS margem_media_pct,
    ROUND(MIN(margem_pct_vgv)        * 100,  2) AS margem_minima_pct,
    ROUND(MAX(margem_pct_vgv)        * 100,  2) AS margem_maxima_pct,
    ROUND(AVG(indice_cobertura),             3) AS cobertura_media,
    ROUND(AVG(ltv_sobre_custo_construcao) * 100, 1) AS ltv_medio_pct,
    ROUND(AVG(prazo_obra_meses),             1) AS prazo_medio_meses,
    CURRENT_TIMESTAMP                             AS created_at
FROM processed_empreendimentos
GROUP BY cenario_viabilidade
ORDER BY margem_media_pct DESC
"""

_SQL_CARTEIRA_REGIAO = """
CREATE OR REPLACE TABLE analytics_carteira_regiao AS
SELECT
    regiao_incc,
    COUNT(*)                                          AS qtd_propostas,
    COUNT(DISTINCT uf_obra)                           AS qtd_ufs,
    COUNT(DISTINCT cidade_obra)                       AS qtd_cidades,
    ROUND(SUM(vgv)                           / 1e6, 2) AS vgv_total_mm,
    ROUND(AVG(vgv)                           / 1e6, 2) AS vgv_medio_mm,
    ROUND(SUM(valor_financiamento_pretendido)/ 1e6, 2) AS financiamento_total_mm,
    ROUND(AVG(margem_pct_vgv)        * 100,  2) AS margem_media_pct,
    ROUND(AVG(indice_cobertura),             3) AS cobertura_media,
    ROUND(AVG(ltv_sobre_custo_construcao) * 100, 1) AS ltv_medio_pct,
    ROUND(AVG(prazo_obra_meses),             1) AS prazo_medio_meses,
    SUM(CASE WHEN cenario_viabilidade = 'Inviável'  THEN 1 ELSE 0 END) AS qtd_inviaveis,
    SUM(CASE WHEN cenario_viabilidade = 'Apertado'  THEN 1 ELSE 0 END) AS qtd_apertados,
    SUM(CASE WHEN cenario_viabilidade = 'Viável'    THEN 1 ELSE 0 END) AS qtd_viaveis,
    ROUND(
        SUM(CASE WHEN cenario_viabilidade = 'Inviável' THEN 1 ELSE 0 END)
        * 100.0 / COUNT(*),
        1
    ) AS pct_inviaveis,
    CURRENT_TIMESTAMP AS created_at
FROM processed_empreendimentos
GROUP BY regiao_incc
ORDER BY vgv_total_mm DESC
"""

_SQL_CARTEIRA_PADRAO = """
CREATE OR REPLACE TABLE analytics_carteira_padrao AS
SELECT
    padrao_acabamento,
    cenario_viabilidade,
    COUNT(*)                                           AS qtd_propostas,
    ROUND(SUM(vgv)                            / 1e6, 2) AS vgv_total_mm,
    ROUND(AVG(area_construida_m2),             0)      AS area_media_m2,
    ROUND(AVG(qtd_unidades),                   0)      AS unidades_medias,
    ROUND(AVG(total_pavimentos),               1)      AS pavimentos_medios,
    ROUND(AVG(vgv / NULLIF(qtd_unidades, 0)) / 1e3, 1) AS ticket_medio_unidade_mil,
    ROUND(AVG(margem_pct_vgv)         * 100,   2)      AS margem_media_pct,
    ROUND(AVG(indice_cobertura),               3)      AS cobertura_media,
    ROUND(AVG(ltv_sobre_custo_construcao) * 100, 1)    AS ltv_medio_pct,
    ROUND(AVG(prazo_obra_meses),               1)      AS prazo_medio_meses,
    CURRENT_TIMESTAMP AS created_at
FROM processed_empreendimentos
GROUP BY padrao_acabamento, cenario_viabilidade
ORDER BY padrao_acabamento, margem_media_pct DESC
"""

_SQL_PIPELINE_MENSAL = """
CREATE OR REPLACE TABLE analytics_pipeline_mensal AS
WITH monthly AS (
    SELECT
        CAST(DATE_TRUNC('month', data_proposta) AS DATE) AS mes_proposta,
        COUNT(*)                                           AS qtd_propostas,
        ROUND(SUM(vgv)                            / 1e6, 2) AS vgv_total_mm,
        ROUND(SUM(valor_financiamento_pretendido) / 1e6, 2) AS financiamento_total_mm,
        ROUND(AVG(margem_pct_vgv) * 100,           2)      AS margem_media_pct,
        ROUND(AVG(indice_cobertura),               3)      AS cobertura_media,
        SUM(CASE WHEN cenario_viabilidade = 'Viável'   THEN 1 ELSE 0 END) AS qtd_viaveis,
        SUM(CASE WHEN cenario_viabilidade = 'Apertado' THEN 1 ELSE 0 END) AS qtd_apertados,
        SUM(CASE WHEN cenario_viabilidade = 'Inviável' THEN 1 ELSE 0 END) AS qtd_inviaveis
    FROM processed_empreendimentos
    GROUP BY CAST(DATE_TRUNC('month', data_proposta) AS DATE)
)
SELECT
    mes_proposta,
    qtd_propostas,
    vgv_total_mm,
    financiamento_total_mm,
    margem_media_pct,
    cobertura_media,
    qtd_viaveis,
    qtd_apertados,
    qtd_inviaveis,
    ROUND(SUM(vgv_total_mm) OVER (ORDER BY mes_proposta), 2) AS vgv_acumulado_mm,
    CURRENT_TIMESTAMP AS created_at
FROM monthly
ORDER BY mes_proposta
"""

# (table_name, sql, output_parquet_name)
_ANALYTICS_PIPELINE: list[tuple[str, str, str]] = [
    ("analytics_carteira_cenario",  _SQL_CARTEIRA_CENARIO,  "analytics_carteira_cenario.parquet"),
    ("analytics_carteira_regiao",   _SQL_CARTEIRA_REGIAO,   "analytics_carteira_regiao.parquet"),
    ("analytics_carteira_padrao",   _SQL_CARTEIRA_PADRAO,   "analytics_carteira_padrao.parquet"),
    ("analytics_pipeline_mensal",   _SQL_PIPELINE_MENSAL,   "analytics_pipeline_mensal.parquet"),
]


# ──────────────────────────────────────────────────────────────────────────────
# Builder
# ──────────────────────────────────────────────────────────────────────────────

def build_portfolio_analytics() -> list[Path]:
    """
    Build all portfolio analytics tables and save Parquet mirrors.

    Returns:
        List of paths to saved Parquet files.

    Raises:
        FileNotFoundError: DuckDB warehouse missing.
        ValueError: Source table absent or analytics table empty.
        RuntimeError: DuckDB execution error.
    """
    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB warehouse not found: {DUCKDB_PATH}. "
            "Run the processing pipeline first."
        )

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Starting portfolio analytics build.")

    output_paths: list[Path] = []

    try:
        with duckdb.connect(str(DUCKDB_PATH)) as conn:
            # Prerequisite: source table must exist
            source_exists = conn.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = 'processed_empreendimentos'
                """
            ).fetchone()[0]

            if not source_exists:
                raise ValueError(
                    "Table processed_empreendimentos not found in DuckDB. "
                    "Run src.processing.process_empreendimentos first."
                )

            for table_name, sql, parquet_name in _ANALYTICS_PIPELINE:
                logger.info("Building table: %s", table_name)

                conn.execute(sql)

                row_count: int = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name}"
                ).fetchone()[0]

                if row_count == 0:
                    raise ValueError(f"Analytics table {table_name} is empty.")

                output_path = PROCESSED_DATA_DIR / parquet_name
                safe_out = str(output_path).replace("\\", "/").replace("'", "''")

                conn.execute(
                    f"COPY {table_name} TO '{safe_out}' (FORMAT PARQUET)"
                )

                logger.info(
                    "Saved | table=%s | rows=%d | path=%s",
                    table_name,
                    row_count,
                    output_path,
                )
                output_paths.append(output_path)

    except duckdb.Error as exc:
        logger.error("DuckDB error during portfolio analytics build: %s", exc)
        raise RuntimeError("Failed to build portfolio analytics.") from exc

    logger.info("All %d analytics tables built successfully.", len(output_paths))
    return output_paths


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "analytics.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    setup_logging()
    try:
        output_paths = build_portfolio_analytics()

        print(f"\n{len(output_paths)} tabelas analytics criadas:")
        for path in output_paths:
            print(f"  {path}")
        print(f"\nDuckDB: {DUCKDB_PATH}")

    except Exception:
        logger.exception("Fatal error during portfolio analytics build.")
        raise


if __name__ == "__main__":
    main()