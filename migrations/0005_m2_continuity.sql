CREATE TABLE IF NOT EXISTS sovereign_sessions(
  session_id text PRIMARY KEY,
  identity_json jsonb NOT NULL,
  scope text NOT NULL,
  objective text NOT NULL,
  critical_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
  operational_state jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_confirmed_action text,
  blockers jsonb NOT NULL DEFAULT '[]'::jsonb,
  pending jsonb NOT NULL DEFAULT '[]'::jsonb,
  next_safe_action text,
  active_authorizations jsonb NOT NULL DEFAULT '[]'::jsonb,
  required_memory_ids text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS external_session_bindings(
  binding_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES sovereign_sessions(session_id) ON DELETE RESTRICT,
  provider text NOT NULL,
  external_session_ref text NOT NULL,
  status text NOT NULL CHECK(status IN ('CURRENT','PENDING_VALIDATION','VALIDATED','SUPERSEDED','ARCHIVED','ABORTED')),
  context_pack_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  validated_at timestamptz,
  superseded_at timestamptz,
  UNIQUE(provider, external_session_ref)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_session_current_binding ON external_session_bindings(session_id) WHERE status='CURRENT';
CREATE INDEX IF NOT EXISTS idx_bindings_session ON external_session_bindings(session_id,created_at DESC);

CREATE TABLE IF NOT EXISTS session_checkpoints(
  checkpoint_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES sovereign_sessions(session_id) ON DELETE RESTRICT,
  state_json jsonb NOT NULL,
  state_sha256 text NOT NULL,
  last_event_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_session_checkpoints_session ON session_checkpoints(session_id,created_at DESC);

CREATE TABLE IF NOT EXISTS context_packs(
  context_pack_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES sovereign_sessions(session_id) ON DELETE RESTRICT,
  checkpoint_id text NOT NULL REFERENCES session_checkpoints(checkpoint_id) ON DELETE RESTRICT,
  context_json jsonb NOT NULL,
  context_sha256 text NOT NULL,
  required_memory_ids text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_context_packs_session ON context_packs(session_id,created_at DESC);

CREATE TABLE IF NOT EXISTS session_rotations(
  rotation_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES sovereign_sessions(session_id) ON DELETE RESTRICT,
  old_binding_id text NOT NULL REFERENCES external_session_bindings(binding_id) ON DELETE RESTRICT,
  new_binding_id text REFERENCES external_session_bindings(binding_id) ON DELETE RESTRICT,
  checkpoint_id text REFERENCES session_checkpoints(checkpoint_id) ON DELETE RESTRICT,
  context_pack_id text REFERENCES context_packs(context_pack_id) ON DELETE RESTRICT,
  status text NOT NULL CHECK(status IN ('REQUESTED','WAITING_SAFE_POINT','CHECKPOINTED','NEW_BOUND','VALIDATED','COMPLETED','ABORTED')),
  reason text NOT NULL,
  safe_point_json jsonb NOT NULL,
  memory_before_mb double precision,
  memory_after_mb double precision,
  memory_released_mb double precision,
  client_close_evidence jsonb,
  failure_reason text,
  requested_at timestamptz NOT NULL DEFAULT now(),
  validated_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_session_rotations_session ON session_rotations(session_id,requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_rotations_status ON session_rotations(status,updated_at);

CREATE TABLE IF NOT EXISTS provider_invocations(
  invocation_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES sovereign_sessions(session_id) ON DELETE RESTRICT,
  binding_id text REFERENCES external_session_bindings(binding_id) ON DELETE SET NULL,
  provider text NOT NULL,
  model text NOT NULL,
  request_sha256 text NOT NULL,
  response_sha256 text,
  observed_context_sha256 text,
  observed_checkpoint_id text,
  status text NOT NULL CHECK(status IN ('REQUESTED','SUCCEEDED','FAILED')),
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_provider_invocations_session ON provider_invocations(session_id,created_at DESC);

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.5.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
