-- Esquema inicial para almacenar evaluaciones diarias de Confluence.
-- Los IDs externos se guardan como texto para no depender de su formato.

CREATE TABLE confluence_spaces (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    confluence_space_id TEXT NOT NULL UNIQUE,
    space_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    confluence_status TEXT NOT NULL DEFAULT 'current',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE confluence_pages (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    confluence_page_id TEXT NOT NULL UNIQUE,
    space_id BIGINT NOT NULL REFERENCES confluence_spaces (id),
    title TEXT NOT NULL,
    page_url TEXT NOT NULL,
    confluence_status TEXT NOT NULL DEFAULT 'current',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX confluence_pages_space_id_idx
    ON confluence_pages (space_id);

CREATE TABLE page_evaluations (
    evaluation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    page_id BIGINT NOT NULL REFERENCES confluence_pages (id),
    evaluation_date DATE NOT NULL DEFAULT CURRENT_DATE,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    author_account_id TEXT,
    author_exists BOOLEAN,
    positive_comments_count INTEGER,
    negative_comments_count INTEGER,
    confluence_updated_at TIMESTAMPTZ,
    likes_count INTEGER,
    spelling_errors_count INTEGER,
    valid_links_count INTEGER,
    invalid_links_count INTEGER,
    author_exists_score NUMERIC(5, 2),
    comments_score NUMERIC(5, 2),
    freshness_score NUMERIC(5, 2),
    structure_score NUMERIC(5, 2),
    likes_score NUMERIC(5, 2),
    spelling_score NUMERIC(5, 2),
    links_score NUMERIC(5, 2),
    evaluation_status TEXT NOT NULL DEFAULT 'completed',
    error_message TEXT,
    scoring_version TEXT NOT NULL DEFAULT 'v1',
    total_score NUMERIC(5, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT page_evaluations_one_per_day
        UNIQUE (page_id, evaluation_date)
);

CREATE INDEX page_evaluations_date_idx
    ON page_evaluations (evaluation_date);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE TRIGGER confluence_spaces_set_updated_at
    BEFORE UPDATE ON confluence_spaces
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER confluence_pages_set_updated_at
    BEFORE UPDATE ON confluence_pages
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER page_evaluations_set_updated_at
    BEFORE UPDATE ON page_evaluations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE confluence_spaces IS
    'Catálogo de espacios de Confluence conocidos por el evaluador.';
COMMENT ON TABLE confluence_pages IS
    'Páginas de Confluence registradas y asociadas a su espacio.';
COMMENT ON TABLE page_evaluations IS
    'Historial de mediciones y puntajes de evaluación de cada página.';

COMMENT ON COLUMN confluence_spaces.id IS
    'Identificador interno autoincremental del espacio.';
COMMENT ON COLUMN confluence_spaces.confluence_space_id IS
    'Identificador del espacio asignado por Confluence.';
COMMENT ON COLUMN confluence_spaces.space_key IS
    'Clave única del espacio en Confluence.';
COMMENT ON COLUMN confluence_spaces.name IS
    'Nombre visible del espacio.';
COMMENT ON COLUMN confluence_spaces.confluence_status IS
    'Estado actual del espacio reportado por Confluence.';
COMMENT ON COLUMN confluence_spaces.created_at IS
    'Fecha y hora en que el registro del espacio se creó en esta base de datos.';
COMMENT ON COLUMN confluence_spaces.updated_at IS
    'Fecha y hora de la última modificación del registro del espacio en esta base de datos.';

COMMENT ON COLUMN confluence_pages.id IS
    'Identificador interno autoincremental de la página.';
COMMENT ON COLUMN confluence_pages.confluence_page_id IS
    'Identificador de la página asignado por Confluence.';
COMMENT ON COLUMN confluence_pages.space_id IS
    'Identificador interno del espacio al que pertenece esta página.';
COMMENT ON COLUMN confluence_pages.title IS
    'Título actual de la página en Confluence.';
COMMENT ON COLUMN confluence_pages.page_url IS
    'URL de acceso a la página en Confluence.';
COMMENT ON COLUMN confluence_pages.confluence_status IS
    'Estado actual de la página reportado por Confluence.';
COMMENT ON COLUMN confluence_pages.created_at IS
    'Fecha y hora en que el registro de la página se creó en esta base de datos.';
COMMENT ON COLUMN confluence_pages.updated_at IS
    'Fecha y hora de la última modificación del registro de la página en esta base de datos.';

COMMENT ON COLUMN page_evaluations.evaluation_id IS
    'Identificador interno autoincremental de la evaluación.';
COMMENT ON COLUMN page_evaluations.page_id IS
    'Identificador interno de la página evaluada.';
COMMENT ON COLUMN page_evaluations.evaluation_date IS
    'Día lógico de evaluación; se registra como máximo una evaluación por página y día.';
COMMENT ON COLUMN page_evaluations.evaluated_at IS
    'Fecha y hora exactas en que se ejecutó esta evaluación.';
COMMENT ON COLUMN page_evaluations.author_account_id IS
    'Identificador de cuenta del autor de la página observado durante la evaluación.';
COMMENT ON COLUMN page_evaluations.author_exists IS
    'Indica si el autor observado existe como usuario de Confluence.';
COMMENT ON COLUMN page_evaluations.positive_comments_count IS
    'Cantidad de comentarios clasificados como positivos durante la evaluación.';
COMMENT ON COLUMN page_evaluations.negative_comments_count IS
    'Cantidad de comentarios clasificados como negativos durante la evaluación.';
COMMENT ON COLUMN page_evaluations.confluence_updated_at IS
    'Fecha y hora de última actualización de la página reportada por Confluence.';
COMMENT ON COLUMN page_evaluations.likes_count IS
    'Cantidad de likes observada durante la evaluación.';
COMMENT ON COLUMN page_evaluations.spelling_errors_count IS
    'Cantidad de errores ortográficos detectados durante la evaluación.';
COMMENT ON COLUMN page_evaluations.valid_links_count IS
    'Cantidad de enlaces comprobados como válidos durante la evaluación.';
COMMENT ON COLUMN page_evaluations.invalid_links_count IS
    'Cantidad de enlaces comprobados como inválidos durante la evaluación.';
COMMENT ON COLUMN page_evaluations.author_exists_score IS
    'Puntaje de 0 a 100 del criterio de existencia del autor.';
COMMENT ON COLUMN page_evaluations.comments_score IS
    'Puntaje de 0 a 100 del criterio de comentarios positivos y negativos.';
COMMENT ON COLUMN page_evaluations.freshness_score IS
    'Puntaje de 0 a 100 del criterio de vigencia según la fecha de actualización.';
COMMENT ON COLUMN page_evaluations.structure_score IS
    'Puntaje de 0 a 100 del criterio de estructura documental.';
COMMENT ON COLUMN page_evaluations.likes_score IS
    'Puntaje de 0 a 100 del criterio de cantidad de likes.';
COMMENT ON COLUMN page_evaluations.spelling_score IS
    'Puntaje de 0 a 100 del criterio de ortografía.';
COMMENT ON COLUMN page_evaluations.links_score IS
    'Puntaje de 0 a 100 del criterio de enlaces válidos e inválidos.';
COMMENT ON COLUMN page_evaluations.evaluation_status IS
    'Estado del proceso de evaluación, gestionado y validado por el servicio.';
COMMENT ON COLUMN page_evaluations.error_message IS
    'Descripción del error si el servicio no pudo completar la evaluación.';
COMMENT ON COLUMN page_evaluations.scoring_version IS
    'Versión de la fórmula y pesos utilizados para calcular el puntaje total.';
COMMENT ON COLUMN page_evaluations.total_score IS
    'Puntaje total ponderado de 0 a 100 calculado y guardado por el servicio.';
COMMENT ON COLUMN page_evaluations.created_at IS
    'Fecha y hora en que el registro de evaluación se creó en esta base de datos.';
COMMENT ON COLUMN page_evaluations.updated_at IS
    'Fecha y hora de la última modificación del registro de evaluación en esta base de datos.';
