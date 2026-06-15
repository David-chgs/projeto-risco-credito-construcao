"""
generate_mock_deals.py

Generates 50 synthetic real estate development proposals (empreendimentos)
for credit risk model development and portfolio stress-testing.

Financial coherence model
─────────────────────────
VGV (Valor Geral de Vendas) is the anchor: the total revenue potential if
every unit sells at full market price. All cost components are computed as
controlled fractions of VGV so that the margin identity always holds:

    VGV
    └─ custo_terreno      = VGV × land_pct          (padrão-controlled)
    └─ custo_construcao   = VGV × construction_pct  (scenario-controlled)
    └─ outras_despesas    = VGV × expenses_pct       (padrão-controlled)
    └─ imposto_estimado   = VGV × tax_pct            (padrão-controlled)
    ─────────────────────────────────────────────────
    margem_inicial        = VGV − all costs above

    valor_financiamento_pretendido = custo_construcao × [0.60, 0.80]
        (mirrors CEF/CAIXA LTV: bank finances up to 80 % of construction cost,
         not the full VGV — the land and developer equity are the collateral)

Three intentional scenario classes drive the construction_pct distribution:
    Viável    → construction_pct ∈ [0.40, 0.50] → margem ≈  15–28 % of VGV
    Apertado  → construction_pct ∈ [0.55, 0.65] → margem ≈   1–14 % of VGV
    Inviável  → construction_pct ∈ [0.75, 0.90] → margem < ~ −5 % of VGV

Sampling weights: 70 % Viável / 20 % Apertado / 10 % Inviável.
Edge cases near scenario boundaries may overlap — this is intentional, as
real portfolios contain ambiguous proposals that challenge any credit model.
"""

from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
LOG_DIR = PROJECT_ROOT / "logs"

OUTPUT_PATH = RAW_DATA_DIR / "empreendimentos.parquet"
N_PROPOSALS = 50
RANDOM_SEED = 42

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Reference tables
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _CityInfo:
    uf: str
    cep_start: int    # 5-digit CEP lower bound (zero-padded on format)
    cep_end: int      # 5-digit CEP upper bound
    regiao_incc: str  # FGV/INCC regional classification — forward join key


_CITY_REGISTRY: dict[str, _CityInfo] = {
    # Norte
    "Manaus":          _CityInfo("AM", 69000, 69299, "Norte"),
    "Belém":           _CityInfo("PA", 66000, 66999, "Norte"),
    # Nordeste
    "Salvador":        _CityInfo("BA", 40000, 45999, "Nordeste"),
    "Fortaleza":       _CityInfo("CE", 60000, 63999, "Nordeste"),
    "Recife":          _CityInfo("PE", 50000, 56999, "Nordeste"),
    # Centro-Oeste
    "Brasília":        _CityInfo("DF", 70000, 73699, "Centro-Oeste"),
    "Goiânia":         _CityInfo("GO", 74000, 76999, "Centro-Oeste"),
    "Cuiabá":          _CityInfo("MT", 78000, 78899, "Centro-Oeste"),
    # Sudeste — higher sampling weight reflects real origination volumes
    "São Paulo":       _CityInfo("SP",  1000,  9999, "Sudeste"),
    "Campinas":        _CityInfo("SP", 13000, 13999, "Sudeste"),
    "Rio de Janeiro":  _CityInfo("RJ", 20000, 28999, "Sudeste"),
    "Belo Horizonte":  _CityInfo("MG", 30000, 34999, "Sudeste"),
    "Vitória":         _CityInfo("ES", 29000, 29299, "Sudeste"),
    # Sul
    "Curitiba":        _CityInfo("PR", 80000, 83999, "Sul"),
    "Porto Alegre":    _CityInfo("RS", 90000, 91999, "Sul"),
    "Florianópolis":   _CityInfo("SC", 88000, 88099, "Sul"),
}

_CITY_NAMES: list[str] = list(_CITY_REGISTRY.keys())
_CITY_WEIGHTS: list[float] = [
    1.0, 1.0,                    # Norte
    1.5, 1.5, 1.5,               # Nordeste
    1.5, 1.0, 1.0,               # Centro-Oeste
    4.0, 2.0, 3.0, 1.5, 1.0,    # Sudeste
    2.0, 2.0, 1.5,               # Sul
]


@dataclass(frozen=True)
class _PadraoSpec:
    """Physical and financial parameters that vary by finishing standard."""
    price_per_m2_range: tuple[int, int]       # R$/m² sale price (market)
    area_per_unit_range: tuple[int, int]      # useful area per unit (m²)
    units_per_floor_range: tuple[int, int]    # typical units per floor
    max_floors: int                           # hard ceiling on total_pavimentos
    subsolos_range: tuple[int, int]
    tax_pct_range: tuple[float, float]        # imposto / VGV  (RET ≈ 4%, LP ≈ 8%)
    expenses_pct_range: tuple[float, float]   # outras_despesas / VGV
    land_pct_range: tuple[float, float]       # custo_terreno / VGV


_PADRÃO_SPECS: dict[str, _PadraoSpec] = {
    "Alto": _PadraoSpec(
        price_per_m2_range=(9_000, 16_000),
        area_per_unit_range=(80, 200),
        units_per_floor_range=(2, 4),
        max_floors=30,
        subsolos_range=(1, 3),
        tax_pct_range=(0.05, 0.08),
        expenses_pct_range=(0.07, 0.12),
        land_pct_range=(0.12, 0.20),
    ),
    "Médio": _PadraoSpec(
        price_per_m2_range=(5_000, 9_000),
        area_per_unit_range=(50, 95),
        units_per_floor_range=(4, 8),
        max_floors=20,
        subsolos_range=(0, 1),
        tax_pct_range=(0.05, 0.07),
        expenses_pct_range=(0.06, 0.10),
        land_pct_range=(0.10, 0.18),
    ),
    "Econômico": _PadraoSpec(
        price_per_m2_range=(2_800, 5_000),
        area_per_unit_range=(35, 65),
        units_per_floor_range=(6, 12),
        max_floors=10,
        subsolos_range=(0, 0),
        tax_pct_range=(0.04, 0.06),
        expenses_pct_range=(0.05, 0.08),
        land_pct_range=(0.08, 0.15),
    ),
}


@dataclass(frozen=True)
class _ScenarioCostRatios:
    """Construction cost pressure range (custo_construcao / VGV) per scenario class."""
    construction_pct_range: tuple[float, float]


_CENARIO_RATIOS: dict[str, _ScenarioCostRatios] = {
    "Viável":   _ScenarioCostRatios((0.40, 0.50)),
    "Apertado": _ScenarioCostRatios((0.55, 0.65)),
    "Inviável": _ScenarioCostRatios((0.75, 0.90)),
}


# ──────────────────────────────────────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────────────────────────────────────

def _rand_date_past_year() -> date:
    return date.today() - timedelta(days=random.randint(0, 364))


def _format_cep(city: _CityInfo) -> str:
    prefix = random.randint(city.cep_start, city.cep_end)
    suffix = random.randint(0, 999)
    return f"{prefix:05d}-{suffix:03d}"


def _generate_single_deal(cenario: str) -> dict:
    city_name = random.choices(_CITY_NAMES, weights=_CITY_WEIGHTS, k=1)[0]
    city      = _CITY_REGISTRY[city_name]
    padrao    = random.choice(["Alto", "Médio", "Econômico"])
    spec      = _PADRÃO_SPECS[padrao]
    ratios    = _CENARIO_RATIOS[cenario]

    # Physical dimensions
    area_construida  = round(random.uniform(1_000, 10_000), 1)
    area_per_unit    = random.randint(*spec.area_per_unit_range)
    qtd_unidades     = max(4, round(area_construida / area_per_unit))

    # Floor count derived from unit density, capped at padrão ceiling
    units_per_floor  = random.randint(*spec.units_per_floor_range)
    total_pavimentos = min(spec.max_floors, max(2, round(qtd_unidades / units_per_floor)))
    num_subsolos     = random.randint(*spec.subsolos_range)

    # VGV anchor — cast to float so pandas stores it as float64, consistent with cost fields
    preco_m2 = random.randint(*spec.price_per_m2_range)
    vgv      = float(qtd_unidades * area_per_unit * preco_m2)

    # Cost components — all expressed as fractions of VGV
    construction_pct = random.uniform(*ratios.construction_pct_range)
    land_pct         = random.uniform(*spec.land_pct_range)
    expenses_pct     = random.uniform(*spec.expenses_pct_range)
    tax_pct          = random.uniform(*spec.tax_pct_range)

    custo_construcao = round(vgv * construction_pct, 2)
    custo_terreno    = round(vgv * land_pct, 2)
    outras_despesas  = round(vgv * expenses_pct, 2)
    # imposto stored in R$ — rate (tax_pct) varies by regime: RET=4%, Lucro Presumido≈8%
    imposto_estimado = round(vgv * tax_pct, 2)
    margem_inicial   = round(
        vgv - custo_construcao - custo_terreno - outras_despesas - imposto_estimado,
        2,
    )

    # Credit request: LTV applied to construction cost only (land = developer equity)
    financing_ltv                  = random.uniform(0.60, 0.80)
    valor_financiamento_pretendido = round(custo_construcao * financing_ltv, 2)

    # Timeline
    data_proposta       = _rand_date_past_year()
    data_inicio_obra    = data_proposta + timedelta(days=random.randint(30, 180))
    duration_months     = random.randint(18, 48)
    data_conclusao_obra = data_inicio_obra + timedelta(days=duration_months * 30)

    return {
        "id_proposta":                    str(uuid.uuid4()),
        "data_proposta":                  data_proposta,
        "cep":                            _format_cep(city),
        "cidade_obra":                    city_name,
        "uf_obra":                        city.uf,
        "regiao_incc":                    city.regiao_incc,
        "padrao_acabamento":              padrao,
        "cenario_viabilidade":            cenario,
        "area_construida_m2":             area_construida,
        "qtd_unidades":                   qtd_unidades,
        "total_pavimentos":               total_pavimentos,
        "num_subsolos":                   num_subsolos,
        "data_inicio_obra":               data_inicio_obra,
        "data_conclusao_obra":            data_conclusao_obra,
        "vgv":                            vgv,
        "custo_terreno":                  custo_terreno,
        "custo_construcao":               custo_construcao,
        "outras_despesas":                outras_despesas,
        "imposto_estimado":               imposto_estimado,
        "valor_financiamento_pretendido": valor_financiamento_pretendido,
        "margem_inicial":                 margem_inicial,
    }


def _generate_dataset(n: int = N_PROPOSALS) -> pd.DataFrame:
    random.seed(RANDOM_SEED)
    cenarios = random.choices(
        ["Viável", "Apertado", "Inviável"],
        weights=[70, 20, 10],
        k=n,
    )
    records = [_generate_single_deal(cenario) for cenario in cenarios]
    df = pd.DataFrame(records)

    # Explicit datetime64 cast — Python date objects serialize as object dtype without this
    for col in ("data_proposta", "data_inicio_obra", "data_conclusao_obra"):
        df[col] = pd.to_datetime(df[col])

    df = df.sort_values("data_proposta").reset_index(drop=True)

    distribution = df["cenario_viabilidade"].value_counts().to_dict()
    logger.info(
        "Dataset gerado | propostas=%d | distribuicao=%s",
        len(df),
        distribution,
    )
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Public interface
# ──────────────────────────────────────────────────────────────────────────────

def save_raw_deals(
    df: pd.DataFrame,
    output_path: Path = OUTPUT_PATH,
) -> Path:
    """
    Persist the proposals DataFrame as Parquet in data/raw/.

    Args:
        df: Generated proposals dataset.
        output_path: Destination Parquet file path.

    Returns:
        Resolved path to the saved file.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        size_kb = output_path.stat().st_size / 1_024
        logger.info(
            "Parquet salvo | path=%s | linhas=%d | tamanho=%.1f KB",
            output_path,
            len(df),
            size_kb,
        )
        return output_path

    except PermissionError as exc:
        logger.error("Permissao negada ao escrever em %s", output_path)
        raise RuntimeError(f"Sem permissao para gravar em {output_path}.") from exc

    except OSError as exc:
        logger.error("Erro de sistema ao gravar Parquet: %s", exc)
        raise RuntimeError("Falha ao persistir o dataset de empreendimentos.") from exc


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "ingestion.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    setup_logging()
    logger.info(
        "Iniciando geracao de propostas mock | n=%d | seed=%d",
        N_PROPOSALS,
        RANDOM_SEED,
    )
    try:
        df   = _generate_dataset(n=N_PROPOSALS)
        path = save_raw_deals(df)

        print(f"\nDataset salvo em: {path}")
        print("\n-- Resumo por cenario de viabilidade --")
        summary = (
            df.groupby("cenario_viabilidade")[["vgv", "margem_inicial"]]
            .agg(["count", "mean", "min", "max"])
            .round(2)
        )
        print(summary.to_string())

    except Exception:
        logger.exception("Erro fatal na geracao de mock deals.")
        raise


if __name__ == "__main__":
    main()