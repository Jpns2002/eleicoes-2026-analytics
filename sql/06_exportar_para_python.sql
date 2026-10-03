-- ============================================================
-- 06 - EXPORTAÇÃO PARA O PYTHON
-- Uma linha por pesquisa e candidato. Rode no Athena, use
-- "Baixar CSV dos resultados" e salve como
-- dados_processados/pesquisas_comparaveis.csv
-- ============================================================

SELECT id_pesquisa,
       instituto,
       candidato,
       MAX(data_fim) AS data_fim,
       MAX(tamanho_amostra) AS amostra,
       AVG(percentual) AS pct
FROM eleicoes2026.vw_pesquisas_comparaveis
WHERE candidato IN ('Lula', 'Flávio', 'Cury', 'Renan', 'Caiado', 'Zema')
GROUP BY id_pesquisa, instituto, candidato;
