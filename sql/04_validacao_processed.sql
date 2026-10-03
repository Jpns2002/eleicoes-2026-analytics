-- ============================================================
-- 04 - VALIDAÇÃO DA CAMADA PROCESSED
-- Esperado: 0 linhas sem data e 0 pesquisas com início depois do fim.
-- ============================================================

SELECT COUNT(*) AS registros,
       COUNT(DISTINCT id_pesquisa) AS pesquisas,
       COUNT_IF(data_inicio IS NULL OR data_fim IS NULL) AS linhas_sem_data,
       COUNT(DISTINCT CASE WHEN data_inicio > data_fim THEN id_pesquisa END) AS pesquisas_invertidas,
       MIN(data_inicio) AS primeira,
       MAX(data_fim) AS ultima
FROM eleicoes2026.processed_pesquisas;

-- Se houver datas invertidas: ver o texto original que escapou do padrão
SELECT DISTINCT r.data_pesquisa, p.data_inicio, p.data_fim
FROM eleicoes2026.processed_pesquisas p
JOIN eleicoes2026.raw_fonte_wikipedia r
  ON p.id_pesquisa = r.id_pesquisa
 AND r.data_coleta = p.coleta_origem
WHERE p.data_inicio > p.data_fim;
