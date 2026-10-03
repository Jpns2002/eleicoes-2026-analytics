-- ============================================================
-- 05 - ANÁLISES
-- Peso de cada pesquisa = LEAST(amostra, 3000): evita que pesquisas
-- gigantes (ex.: 40.500 entrevistas) dominem a média.
-- ============================================================

-- Ranking dos últimos 21 dias (só cenários comparáveis)
WITH por_pesquisa AS (
  SELECT id_pesquisa, candidato, partido,
         MAX(data_fim) AS data_fim,
         MAX(tamanho_amostra) AS amostra,
         AVG(percentual) AS pct
  FROM eleicoes2026.vw_pesquisas_comparaveis
  GROUP BY id_pesquisa, candidato, partido
)
SELECT candidato, partido,
       COUNT(*) AS pesquisas,
       ROUND(SUM(pct * LEAST(amostra, 3000)) / SUM(LEAST(amostra, 3000)), 1) AS media_ponderada
FROM por_pesquisa
WHERE data_fim >= date_add('day', -21, current_date)
GROUP BY candidato, partido
HAVING COUNT(*) >= 5
ORDER BY media_ponderada DESC;

-- Evolução semanal com window function (LAG)
WITH por_pesquisa AS (
  SELECT id_pesquisa, candidato,
         MAX(data_fim) AS data_fim,
         MAX(tamanho_amostra) AS amostra,
         AVG(percentual) AS pct
  FROM eleicoes2026.processed_pesquisas
  GROUP BY id_pesquisa, candidato
),
semanal AS (
  SELECT candidato,
         date_trunc('week', data_fim) AS semana,
         COUNT(*) AS pesquisas,
         SUM(pct * LEAST(amostra, 3000)) / SUM(LEAST(amostra, 3000)) AS media_pond
  FROM por_pesquisa
  WHERE candidato IN ('Lula', 'Flávio', 'Caiado', 'Zema', 'Renan', 'Cury')
  GROUP BY candidato, date_trunc('week', data_fim)
)
SELECT candidato, semana, pesquisas,
       ROUND(media_pond, 1) AS media_pond,
       ROUND(media_pond - LAG(media_pond) OVER (
               PARTITION BY candidato ORDER BY semana), 1) AS variacao
FROM semanal
ORDER BY candidato, semana;

-- Lula x Flávio por instituto (diagnóstico de efeito de instituto)
WITH por_pesquisa AS (
  SELECT id_pesquisa, instituto, candidato,
         MAX(data_fim) AS data_fim,
         MAX(tamanho_amostra) AS amostra,
         AVG(percentual) AS pct
  FROM eleicoes2026.processed_pesquisas
  WHERE candidato IN ('Lula', 'Flávio')
  GROUP BY id_pesquisa, instituto, candidato
)
SELECT instituto,
       COUNT(DISTINCT id_pesquisa) AS pesquisas,
       ROUND(AVG(amostra)) AS amostra_media,
       MAX(amostra) AS amostra_max,
       ROUND(AVG(CASE WHEN candidato = 'Lula' THEN pct END), 1) AS lula,
       ROUND(AVG(CASE WHEN candidato = 'Flávio' THEN pct END), 1) AS flavio
FROM por_pesquisa
WHERE data_fim >= date_add('day', -21, current_date)
GROUP BY instituto
ORDER BY pesquisas DESC;
