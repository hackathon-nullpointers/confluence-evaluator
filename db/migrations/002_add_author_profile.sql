ALTER TABLE page_evaluations
    ADD COLUMN IF NOT EXISTS author_display_name TEXT,
    ADD COLUMN IF NOT EXISTS author_email TEXT;

COMMENT ON COLUMN page_evaluations.author_display_name IS
    'Nombre visible del autor según el perfil de Confluence al momento de evaluar.';
COMMENT ON COLUMN page_evaluations.author_email IS
    'Correo visible del autor según los permisos y la configuración de privacidad de Confluence.';
