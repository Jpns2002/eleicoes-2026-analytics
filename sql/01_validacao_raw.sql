-- ============================================================
-- 01 - VALIDAÇÃO DA CAMADA RAW
-- Tabela: eleicoes2026.raw_fonte_wikipedia (criada pelo Glue Crawler)
-- O Athena executa UM comando por vez: rode cada consulta separadamente.
-- ============================================================

-- Registrar partições novas depois de cada coleta (sem custo de crawler)
MSCK REPAIR TABLE eleicoes2026.raw_fonte_wikipedia;

-- Quantos registros cada coleta trouxe
SELECT data_coleta, COUNT(*) AS registros
FROM eleicoes2026.raw_fonte_wikipedia
GROUP BY data_coleta
ORDER BY data_coleta;

-- Garantir que só há 1º turno na coleta
SELECT seccao_h2,
       COUNT(DISTINCT id_pesquisa) AS pesquisas,
       COUNT(*) AS registros
FROM eleicoes2026.raw_fonte_wikipedia
WHERE data_coleta = '2026-10-01'
GROUP BY seccao_h2;

-- Candidatos e partidos (procurar nomes que não sejam candidatos)
SELECT DISTINCT candidato, partido
FROM eleicoes2026.raw_fonte_wikipedia
ORDER BY candidato;

-- Volume por mês
SELECT mes_referencia,
       COUNT(DISTINCT id_pesquisa) AS pesquisas,
       COUNT(*) AS registros
FROM eleicoes2026.raw_fonte_wikipedia
GROUP BY mes_referencia
ORDER BY registros DESC;

-- Sanidade dos números (célula vazia de CSV vira '' e não NULL)
SELECT COUNT(*) AS registros,
       COUNT_IF(partido IS NULL OR TRIM(partido) = '') AS sem_partido,
       MIN(percentual) AS pct_minimo,
       MAX(percentual) AS pct_maximo
FROM eleicoes2026.raw_fonte_wikipedia;
