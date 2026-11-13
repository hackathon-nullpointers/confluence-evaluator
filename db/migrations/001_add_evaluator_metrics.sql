-- Add fields required by the daily evaluator to an existing schema.
ALTER TABLE page_evaluations
    ADD COLUMN IF NOT EXISTS comments_analyzed_count INTEGER,
    ADD COLUMN IF NOT EXISTS neutral_comments_count INTEGER,
    ADD COLUMN IF NOT EXISTS positive_comment_relevance NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS negative_comment_relevance NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS word_count INTEGER,
    ADD COLUMN IF NOT EXISTS unchecked_links_count INTEGER,
    ADD COLUMN IF NOT EXISTS comparison_group TEXT,
    ADD COLUMN IF NOT EXISTS ai_model TEXT,
    ADD COLUMN IF NOT EXISTS ai_prompt_version TEXT;

COMMENT ON COLUMN page_evaluations.comments_analyzed_count IS
    'Cantidad total de comentarios procesados por el evaluador de sentimiento.';
COMMENT ON COLUMN page_evaluations.neutral_comments_count IS
    'Cantidad de comentarios clasificados como neutrales o irrelevantes durante la evaluación.';
COMMENT ON COLUMN page_evaluations.positive_comment_relevance IS
    'Suma de relevancia de los comentarios positivos usada para calcular comments_score.';
COMMENT ON COLUMN page_evaluations.negative_comment_relevance IS
    'Suma de relevancia de los comentarios negativos usada para calcular comments_score.';
COMMENT ON COLUMN page_evaluations.word_count IS
    'Cantidad de palabras evaluadas para normalizar el puntaje de ortografía.';
COMMENT ON COLUMN page_evaluations.unchecked_links_count IS
    'Cantidad de enlaces omitidos por no ser verificables de forma segura o por fallo transitorio.';
COMMENT ON COLUMN page_evaluations.comparison_group IS
    'Grupo semántico utilizado para comparar likes con páginas similares.';
COMMENT ON COLUMN page_evaluations.ai_model IS
    'Modelo de GitHub Copilot seleccionado para los criterios evaluados con IA.';
COMMENT ON COLUMN page_evaluations.ai_prompt_version IS
    'Versión del prompt estructurado usado por el evaluador de IA.';
