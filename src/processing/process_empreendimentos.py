"""
process_empreendimentos.py

Reads raw empreendimentos Parquet, applies explicit type casting, computes
derived credit risk indicators, and persists the result into both DuckDB
and a Parquet mirror.

Derived indicators
──────────────────
custo_total                = sum of all cost components (R$)
prazo_obra_meses           = construction duration in full months
margem_pct_vgv             = margem_inicial / VGV       (core profitability ratio)
indice_cobertura           = VGV / custo_total           (coverage; must be > 1.0 for viable)
ltv_sobre_custo_construcao = financiamento / custo_construcao  (bank exposure ratio)

Financial identity check
────────────────────────
Every row must satisfy: ABS((custo_total + margem_inicial) − VGV) ≤ R$ 0.10.
Any violation raises a ValueError — the pipeline does not silently persist corrupt data.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
LOG_DIR = PROJECT_ROOT / "logs"

DUCKDB_PATH = WAREHOUSE_DIR / "credit_risk.duckdb"
RAW_PATH = RAW_DATA_DIR / "empreendimentos.parquet"
PROCESSED_PATH = PROCESSED_DATA_DIR / "empreendimentos.parquet"

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "processing.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _safe_path(path: Path) -> str:
    """Normalize a Windows path for DuckDB SQL string literals."""
    return str(path).replace("\\", "/").replace("'", "''")


def process_empreendimentos() -> Path:
    """
    Process raw empreendimentos into a typed, enriched analytical table.

    Returns:
        Path to the processed Parquet mirror.

    Raises:
        FileNotFoundError: Raw Parquet source does not exist.
        ValueError: Processed table is empty or financial identity is violated.
        RuntimeError: DuckDB or filesystem errors.
    """
    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"Raw file not found: {RAW_PATH}. "
            "Run src.ingestion.generate_mock_deals first."
        )

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)

    safe_raw = _safe_path(RAW_PATH)
    safe_out = _safe_path(PROCESSED_PATH)

    logger.info("Starting empreendimentos processing | source=%s", RAW_PATH)

    try:
        with duckdb.connect(str(DUCKDB_PATH)) as conn:
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE processed_empreendimentos AS
                SELECT
                    -- Identity
                    CAST(id_proposta AS VARCHAR) AS id_proposta,

                    -- Geography & classification
                    CAST(cep               AS VARCHAR) AS cep,
                    CAST(cidade_obra       AS VARCHAR) AS cidade_obra,
                    CAST(uf_obra           AS VARCHAR) AS uf_obra,
                    CAST(regiao_incc       AS VARCHAR) AS regiao_incc,
                    CAST(padrao_acabamento    AS VARCHAR) AS padrao_acabamento,
                    CAST(cenario_viabilidade  AS VARCHAR) AS cenario_viabilidade,

                    -- Physical dimensions
                    CAST(area_construida_m2 AS DOUBLE)  AS area_construida_m2,
                    CAST(qtd_unidades       AS INTEGER)  AS qtd_unidades,
                    CAST(total_pavimentos   AS INTEGER)  AS total_pavimentos,
                    CAST(num_subsolos       AS INTEGER)  AS num_subsolos,

                    -- Timeline
                    CAST(data_proposta       AS DATE) AS data_proposta,
                    CAST(data_inicio_obra    AS DATE) AS data_inicio_obra,
                    CAST(data_conclusao_obra AS DATE) AS data_conclusao_obra,

                    -- Financials (raw, in BRL)
                    CAST(vgv                             AS DOUBLE) AS vgv,
                    CAST(custo_terreno                   AS DOUBLE) AS custo_terreno,
                    CAST(custo_construcao                AS DOUBLE) AS custo_construcao,
                    CAST(outras_despesas                 AS DOUBLE) AS outras_despesas,
                    CAST(imposto_estimado                AS DOUBLE) AS imposto_estimado,
                    CAST(valor_financiamento_pretendido  AS DOUBLE) AS valor_financiamento_pretendido,
                    CAST(margem_inicial                  AS DOUBLE) AS margem_inicial,

                    -- ── Derived credit risk indicators ──────────────────────────────────────
                    ROUND(
                        custo_terreno + custo_construcao + outras_despesas + imposto_estimado,
                        2
                    ) AS custo_total,

                    datediff(
                        'month',
                        CAST(data_inicio_obra    AS DATE),
                        CAST(data_conclusao_obra AS DATE)
                    ) AS prazo_obra_meses,

                    ROUND(
                        margem_inicial / NULLIF(vgv, 0),
                        4
                    ) AS margem_pct_vgv,

                    ROUND(
                        vgv / NULLIF(
                            custo_terreno + custo_construcao + outras_despesas + imposto_estimado,
                            0
                        ),
                        4
                    ) AS indice_cobertura,

                    ROUND(
                        valor_financiamento_pretendido / NULLIF(custo_construcao, 0),
                        4
                    ) AS ltv_sobre_custo_construcao

                FROM read_parquet('{safe_raw}')
                WHERE
                    vgv              > 0
                    AND custo_construcao > 0
                    AND id_proposta  IS NOT NULL
                """
            )

            row_count: int = conn.execute(
                "SELECT COUNT(*) FROM processed_empreendimentos"
            ).fetchone()[0]

            if row_count == 0:
                raise ValueError(
                    "processed_empreendimentos is empty after filtering. "
                    "Check that the raw file contains valid records."
                )

            # Financial identity gate: VGV must equal custo_total + margem_inicial
            # within R$ 0.10 tolerance (floating-point rounding allowance).
            identity_violations: int = conn.execute(
                """
                SELECT COUNT(*) FROM processed_empreendimentos
                WHERE ABS((custo_total + margem_inicial) - vgv) > 0.10
                """
            ).fetchone()[0]

            if identity_violations > 0:
                raise ValueError(
                    f"Financial identity violated in {identity_violations} row(s): "
                    "VGV != custo_total + margem_inicial. "
                    "Inspect the raw source for corrupted cost fields."
                )

            conn.execute(
                f"COPY processed_empreendimentos TO '{safe_out}' (FORMAT PARQUET)"
            )

            summary = conn.execute(
                """
                SELECT
                    cenario_viabilidade,
                    COUNT(*)                              AS propostas,
                    ROUND(AVG(margem_pct_vgv)     * 100, 1) AS margem_media_pct,
                    ROUND(AVG(indice_cobertura),       3) AS cobertura_media,
                    ROUND(AVG(ltv_sobre_custo_construcao) * 100, 1) AS ltv_medio_pct,
                    ROUND(AVG(prazo_obra_meses),       1) AS prazo_medio_meses
                FROM processed_empreendimentos
                GROUP BY cenario_viabilidade
                ORDER BY margem_media_pct DESC
                """
            ).fetchall()

    except duckdb.Error as exc:
        logger.error("DuckDB error during empreendimentos processing: %s", exc)
        raise RuntimeError("Failed to process empreendimentos in DuckDB.") from exc

    logger.info(
        "Processed rows=%d | identity_violations=0 | table=processed_empreendimentos",
        row_count,
    )
    logger.info("Parquet mirror saved to %s", PROCESSED_PATH)
    logger.info("DuckDB warehouse updated at %s", DUCKDB_PATH)

    return PROCESSED_PATH, summary


def main() -> None:
    setup_logging()
    try:
        output_path, summary = process_empreendimentos()

        print(f"\nProcessamento concluido: {output_path}")
        print(f"Banco DuckDB atualizado:  {DUCKDB_PATH}")
        print("\n-- Indicadores por cenario de viabilidade --")
        print(
            f"{'Cenario':<12} {'Propostas':>9} {'Margem%':>9} "
            f"{'Cobertura':>10} {'LTV%':>7} {'Prazo(m)':>9}"
        )
        print("-" * 60)
        for row in summary:
            cenario, propostas, margem, cobertura, ltv, prazo = row
            print(
                f"{cenario:<12} {propostas:>9} {margem:>8.1f}% "
                f"{cobertura:>10.3f} {ltv:>6.1f}% {prazo:>9.1f}"
            )

    except Exception:
        logger.exception("Fatal error during empreendimentos processing.")
        raise


if __name__ == "__main__":
    main()