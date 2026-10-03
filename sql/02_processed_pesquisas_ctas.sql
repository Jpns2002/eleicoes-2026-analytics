-- ============================================================
-- 02 - CAMADA PROCESSED (CTAS)
-- Cria eleicoes2026.processed_pesquisas em Parquet:
--   - mantém a versão mais recente de cada pesquisa (dedup entre coletas)
--   - converte textos como "28 Set – 1 Out" em data_inicio e data_fim
--
-- Para refazer: DROP TABLE eleicoes2026.processed_pesquisas;
--   e apagar a pasta processed/pesquisas/ no S3 (o DROP não apaga arquivos).
-- Rode como um único comando.
-- ============================================================

CREATE TABLE eleicoes2026.processed_pesquisas
WITH (
  format = 'PARQUET',
  write_compression = 'SNAPPY',
  external_location = 's3://SEU-BUCKET/processed/pesquisas/'
) AS
WITH ultima_coleta AS (
  SELECT id_pesquisa, MAX(data_coleta) AS data_coleta
  FROM eleicoes2026.raw_fonte_wikipedia
  WHERE seccao_h2 = 'Primeiro turno'
  GROUP BY id_pesquisa
),
dedup AS (
  SELECT r.*
  FROM eleicoes2026.raw_fonte_wikipedia r
  JOIN ultima_coleta u
    ON r.id_pesquisa = u.id_pesquisa
   AND r.data_coleta = u.data_coleta
  WHERE r.seccao_h2 = 'Primeiro turno'
),
limpa AS (
  -- aceita hífen, travessão e travessão longo entre as datas
  SELECT *, regexp_replace(trim(data_pesquisa), '\s*[-–—]\s*', '-') AS d
  FROM dedup
),
partes AS (
  SELECT *,
    regexp_extract(d, '(\d{1,2}) ([A-Za-z]{3})$', 1) AS dia_fim,
    lower(regexp_extract(d, '(\d{1,2}) ([A-Za-z]{3})$', 2)) AS mes_fim_txt,
    regexp_extract(split_part(d, '-', 1), '^(\d{1,2})', 1) AS dia_ini,
    lower(regexp_extract(split_part(d, '-', 1), '([A-Za-z]{3})$', 1)) AS mes_ini_txt
  FROM limpa
),
numeros AS (
  SELECT *,
    array_position(ARRAY['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'],
                   mes_fim_txt) AS mes_fim,
    array_position(ARRAY['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'],
                   COALESCE(mes_ini_txt, mes_fim_txt)) AS mes_ini
  FROM partes
)
SELECT
  id_pesquisa,
  id_cenario,
  TRY(CAST(concat(
        CAST(CASE WHEN mes_ini > mes_fim THEN 2025 ELSE 2026 END AS varchar), '-',
        lpad(CAST(mes_ini AS varchar), 2, '0'), '-',
        lpad(dia_ini, 2, '0')) AS date)) AS data_inicio,
  TRY(CAST(concat(
        '2026-',
        lpad(CAST(mes_fim AS varchar), 2, '0'), '-',
        lpad(dia_fim, 2, '0')) AS date)) AS data_fim,
  contratante_padronizado AS instituto,
  tamanho_amostra,
  margem_erro,
  candidato,
  partido,
  percentual,
  data_coleta AS coleta_origem
FROM numeros;
