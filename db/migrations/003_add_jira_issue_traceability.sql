CREATE TABLE jira_evaluation_issues (
    evaluation_id BIGINT PRIMARY KEY
        REFERENCES page_evaluations (evaluation_id) ON DELETE CASCADE,
    jira_project_key TEXT NOT NULL,
    jira_issue_key TEXT UNIQUE,
    jira_issue_url TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending',
    last_action TEXT,
    feedback_snapshot JSONB,
    sync_attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempted_at TIMESTAMPTZ,
    last_synced_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT jira_evaluation_issues_status_check
        CHECK (sync_status IN ('pending', 'synced', 'failed')),
    CONSTRAINT jira_evaluation_issues_action_check
        CHECK (last_action IS NULL OR last_action IN ('created', 'updated', 'failed')),
    CONSTRAINT jira_evaluation_issues_attempt_count_check
        CHECK (sync_attempt_count >= 0),
    CONSTRAINT jira_evaluation_issues_synced_issue_check
        CHECK (
            sync_status <> 'synced'
            OR (jira_issue_key IS NOT NULL AND jira_issue_url IS NOT NULL)
        )
);

CREATE TRIGGER jira_evaluation_issues_set_updated_at
    BEFORE UPDATE ON jira_evaluation_issues
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE jira_evaluation_issues IS
    'Trazabilidad del ticket Jira sincronizado para cada evaluación de página.';
COMMENT ON COLUMN jira_evaluation_issues.feedback_snapshot IS
    'Copia JSON del motivo, insights y recomendaciones enviados a Jira.';
COMMENT ON COLUMN jira_evaluation_issues.sync_attempt_count IS
    'Cantidad de intentos de sincronización con Jira.';
COMMENT ON COLUMN jira_evaluation_issues.last_error IS
    'Último error ocurrido al generar feedback o sincronizar el ticket Jira.';
