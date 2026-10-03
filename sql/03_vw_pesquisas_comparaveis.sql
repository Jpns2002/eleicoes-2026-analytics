-- ============================================================
-- 03 - VIEW DE CENÁRIOS COMPARÁVEIS
-- Mantém só os cenários que contêm Lula E Flávio, para que a
-- comparação entre eles use sempre a mesma disputa.
-- ============================================================

CREATE OR REPLACE VIEW eleicoes2026.vw_pesquisas_comparaveis AS
WITH cenarios_validos AS (
  SELECT id_cenario
  FROM eleicoes2026.processed_pesquisas
  GROUP BY id_cenario
  HAVING MAX(CASE WHEN candidato = 'Lula' THEN 1 ELSE 0 END) = 1
     AND MAX(CASE WHEN candidato = 'Flávio' THEN 1 ELSE 0 END) = 1
)
SELECT p.*
FROM eleicoes2026.processed_pesquisas p
JOIN cenarios_validos c ON p.id_cenario = c.id_cenario;

-- Diagnóstico de como os cenários se distribuem
WITH cenarios AS (
  SELECT id_pesquisa, id_cenario,
         COUNT(*) AS candidatos,
         MAX(CASE WHEN candidato = 'Lula' THEN 1 ELSE 0 END) AS tem_lula,
         MAX(CASE WHEN candidato = 'Flávio' THEN 1 ELSE 0 END) AS tem_flavio
  FROM eleicoes2026.processed_pesquisas
  GROUP BY id_pesquisa, id_cenario
)
SELECT COUNT(DISTINCT id_pesquisa) AS pesquisas,
       COUNT(*) AS cenarios,
       COUNT_IF(tem_lula = 1 AND tem_flavio = 1) AS com_lula_e_flavio,
       COUNT_IF(tem_lula = 1 AND tem_flavio = 0) AS so_lula,
       COUNT_IF(tem_lula = 0 AND tem_flavio = 1) AS so_flavio,
       ROUND(AVG(candidatos), 1) AS candidatos_por_cenario
FROM cenarios;
