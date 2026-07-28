-- Bind workflow-owned protocol context and completion validation to immutable
-- physical analysis re-runs.  Neither value is part of the hardware payload.

ALTER TABLE analysis.analysis_runs
    ADD COLUMN input_validation_status text NOT NULL DEFAULT 'REJECTED'
        CHECK (input_validation_status IN ('VALIDATED', 'REJECTED')),
    ADD COLUMN protocol_context_sha256 text NOT NULL DEFAULT repeat('0', 64)
        CHECK (protocol_context_sha256 ~ '^[0-9a-f]{64}$');

DO $$
DECLARE
    old_constraint text;
BEGIN
    SELECT conname
      INTO old_constraint
      FROM pg_constraint
     WHERE conrelid = 'analysis.analysis_runs'::regclass
       AND contype = 'u'
       AND pg_get_constraintdef(oid) LIKE
           '%tenant_id, session_id, pipeline_version, algorithm_set_version, model_set_version, report_schema_version, calibration_version, payload_schema_version, protocol_profile_version, input_manifest_sha256, parameters_sha256)%';
    IF old_constraint IS NULL THEN
        RAISE EXCEPTION 'expected analysis_runs recompute identity constraint is missing';
    END IF;
    EXECUTE format('ALTER TABLE analysis.analysis_runs DROP CONSTRAINT %I', old_constraint);
END $$;

ALTER TABLE analysis.analysis_runs
    ADD CONSTRAINT analysis_runs_recompute_identity_unique UNIQUE (
        tenant_id,
        session_id,
        pipeline_version,
        algorithm_set_version,
        model_set_version,
        report_schema_version,
        calibration_version,
        payload_schema_version,
        protocol_profile_version,
        input_validation_status,
        protocol_context_sha256,
        input_manifest_sha256,
        parameters_sha256
    );
