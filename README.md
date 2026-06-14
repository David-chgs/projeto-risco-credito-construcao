# Pipeline de Analise de Risco de Credito e Custo da Construcao Civil

Projeto de dados desenvolvido para simular uma solucao analitica para uma fintech imobiliaria, com foco em risco de credito, indicadores macroeconomicos e custos da construcao civil no Brasil.

O objetivo e construir um pipeline local, reproduzivel e modular, utilizando fontes publicas brasileiras como Banco Central do Brasil, IBGE/SINAPI e indicadores de inflacao/custo da construcao.

## Objetivo do Projeto

Este projeto demonstra a construcao de um pipeline de dados para apoiar analises de uma PropTech ou fintech imobiliaria.

A solucao busca responder perguntas como:

- Como indicadores macroeconomicos impactam o risco de credito imobiliario?
- Como Selic e IPCA evoluem ao longo do tempo?
- Como integrar dados economicos publicos em uma base analitica local?
- Como estruturar um pipeline auditavel com Python, DuckDB e Parquet?

## Stack Tecnologica

- Python
- Pandas
- DuckDB
- Parquet
- Requests
- Streamlit
- Docker, em etapa futura

## Fontes de Dados

### Banco Central do Brasil - SGS

Fonte: Sistema Gerenciador de Series Temporais do Banco Central do Brasil.

Series utilizadas inicialmente:

| Codigo SGS | Nome | Frequencia | Descricao |
|---:|---|---|---|
| 11 | selic_diaria | diaria | Taxa Selic diaria |
| 433 | ipca_mensal | mensal | IPCA variacao mensal |

Outras fontes serao adicionadas em etapas futuras, incluindo INCC e SINAPI/IBGE.

## Arquitetura de Dados

O projeto segue uma arquitetura em camadas:

    Fonte publica
        ->
    data/raw
        ->
    data/processed
        ->
    data/warehouse
        ->
    dashboard analitico

### Camada Raw

A camada `data/raw` armazena os dados brutos recebidos das fontes externas.

Formatos utilizados:

- JSON, para preservar a resposta original da API
- Parquet, para leitura eficiente em etapas posteriores

### Camada Processed

A camada `data/processed` armazena dados tratados, tipados e padronizados.

Arquivo atual:

    data/processed/bacen_series.parquet

Colunas principais:

| Coluna | Descricao |
|---|---|
| reference_date | Data de referencia do indicador |
| series_code | Codigo da serie no SGS/BACEN |
| series_name | Nome padronizado da serie |
| value | Valor numerico do indicador |
| source | Fonte do dado |
| frequency | Frequencia da serie |

### Camada Warehouse

A camada `data/warehouse` armazena o banco analitico local em DuckDB.

Arquivo gerado:

    data/warehouse/credit_risk.duckdb

Tabela principal atual:

    processed_bacen_series

## Estrutura do Projeto

    projeto-risco-credito-construcao/
    |
    +-- data/
    |   +-- raw/
    |   +-- processed/
    |   +-- external/
    |   +-- warehouse/
    |
    +-- dashboards/
    +-- logs/
    +-- notebooks/
    +-- src/
    |   +-- config/
    |   |   +-- series_config.py
    |   +-- ingestion/
    |   |   +-- fetch_bacen_sgs.py
    |   +-- processing/
    |   |   +-- process_bacen_sgs.py
    |   +-- utils/
    |
    +-- tests/
    +-- .gitignore
    +-- README.md
    +-- requirements.txt

## Como Executar o Projeto

### 1. Criar ambiente virtual

    python -m venv .venv

### 2. Ativar ambiente virtual

    .\.venv\Scripts\Activate.ps1

### 3. Instalar dependencias

    pip install -r requirements.txt

### 4. Executar ingestao dos dados do BACEN

    python -m src.ingestion.fetch_bacen_sgs

### 5. Executar processamento dos dados

    python -m src.processing.process_bacen_sgs

Esse comando gera:

    data/processed/bacen_series.parquet
    data/warehouse/credit_risk.duckdb

## Validacao Rapida com DuckDB

Abra o Python:

    python

Depois execute:

    import duckdb

    con = duckdb.connect("data/warehouse/credit_risk.duckdb")

    con.sql("""
    SELECT
        series_code,
        series_name,
        frequency,
        MIN(reference_date) AS min_date,
        MAX(reference_date) AS max_date,
        COUNT(*) AS total_rows,
        AVG(value) AS avg_value
    FROM processed_bacen_series
    GROUP BY
        series_code,
        series_name,
        frequency
    ORDER BY series_code
    """).show()

    con.close()

## Status Atual

O projeto atualmente possui:

- Estrutura inicial de pastas
- Ambiente virtual configurado
- Ingestao da API SGS do Banco Central
- Salvamento de dados brutos em JSON e Parquet
- Processamento padronizado com DuckDB
- Tabela analitica local com Selic diaria e IPCA mensal

## Proximas Etapas

- Adicionar testes automatizados
- Melhorar configuracoes do pipeline
- Incluir novas fontes, como INCC e SINAPI/IBGE
- Criar indicadores analiticos de risco
- Desenvolver dashboard em Streamlit
- Containerizar o projeto com Docker na etapa final

## Testes Automatizados

O projeto utiliza `pytest` para validar regras basicas de configuracao e processamento.

Para executar os testes:

    python -m pytest -v

Atualmente os testes validam:

- Existencia de configuracoes BACEN
- Unicidade dos codigos SGS
- Padrao de nomes em snake_case
- Formato das datas de inicio e fim
- Frequencias suportadas
- Selecao do arquivo Parquet bruto mais recente

## Camada Analitica

O projeto tambem gera uma tabela analitica mensal com indicadores macroeconomicos derivados.

Tabela DuckDB:

    analytics_macro_indicators

Arquivo Parquet:

    data/processed/analytics_macro_indicators.parquet

Indicadores atuais:

- Selic mensal acumulada
- IPCA mensal
- Proxy simples de juro real mensal

Essa camada sera usada futuramente para apoiar analises de risco de credito imobiliario e visualizacoes no dashboard.
