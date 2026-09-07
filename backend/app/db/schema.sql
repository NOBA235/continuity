-- Continuity.Agent -- ClickHouse schema
-- Native ClickHouse DDL (MergeTree family engines, no generic-SQL substitutes).
-- Applied idempotently at startup by app/db/migrate.py.

CREATE DATABASE IF NOT EXISTS continuity_agent;

-- Accounts for the dashboard/API. Passwords are bcrypt hashes -- never
-- plaintext, never reversible (see app/auth/security.py). `role` gates
-- which endpoints an account may call (see app/auth/dependencies.py).
-- `version` (not created_at) drives ReplacingMergeTree dedup, so that
-- re-inserting a row to record a login never clobbers the original
-- created_at -- see app/services/user_store.py.
CREATE TABLE IF NOT EXISTS continuity_agent.users
(
    user_id         UUID DEFAULT generateUUIDv4(),
    email           String,
    hashed_password String,
    display_name    String DEFAULT '',
    role            Enum8('viewer' = 1, 'editor' = 2, 'supervisor' = 3),
    is_active       UInt8 DEFAULT 1,
    created_at      DateTime,
    last_login_at   Nullable(DateTime),
    version         UInt64 DEFAULT toUnixTimestamp64Micro(now64(6))
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (email);

-- One row per (scene, take, frame): the atomic unit of continuity QA.
-- `embedding` holds a Gemini Embedding vector of the keyframe image, used
-- for nearest-neighbour "does this prop/costume look different" comparisons
-- across takes of the same scene.
CREATE TABLE IF NOT EXISTS continuity_agent.frame_metadata
(
    scene_id             String,
    take_id              String,
    video_id             String,
    timecode             String,                 -- SMPTE timecode, e.g. 01:02:03:12
    frame_number         UInt32,
    timestamp            DateTime,               -- wall-clock offset into the source video
    actor_id             String,
    wardrobe_description String,
    prop_list            Array(String),
    prop_states          String,                 -- JSON string, e.g. {"glass_fill_level": "50%"}
    lighting_vector      Array(Float32),          -- [key_intensity, fill_intensity, color_temp_k/1000, ...]
    embedding            Array(Float32),
    confidence_score     Float32,
    gemini_model         LowCardinality(String),  -- model id that produced this row, for auditability
    ingested_at          DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (scene_id, take_id, frame_number)
PARTITION BY toYYYYMM(timestamp);

-- Flags raised by the continuity agent (or a human reviewer) comparing two
-- frames -- usually two takes of the same scene, or two frames within the
-- same take that should be visually consistent.
CREATE TABLE IF NOT EXISTS continuity_agent.continuity_anomalies
(
    anomaly_id        UUID DEFAULT generateUUIDv4(),
    scene_id          String,
    take_id           String,
    compared_take_id  String,                    -- the take/frame it was diffed against
    frame_number_a    UInt32,
    frame_number_b    UInt32,
    timecode_a        String,
    timecode_b        String,
    anomaly_type      Enum8(
                          'prop_mismatch'     = 1,
                          'wardrobe_mismatch' = 2,
                          'position_mismatch' = 3,
                          'lighting_mismatch' = 4,
                          'continuity_other'  = 5
                      ),
    description       String,
    severity          Enum8('low' = 1, 'medium' = 2, 'high' = 3, 'critical' = 4),
    detected_by_agent LowCardinality(String),
    confidence_score  Float32,
    resolved          UInt8 DEFAULT 0,
    resolved_note     String DEFAULT '',
    detected_at       DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (scene_id, take_id, detected_at);

-- Structured trace of every agent run: one row per reasoning/tool-call step,
-- rendered by the frontend's "Agent Trace" panel.
CREATE TABLE IF NOT EXISTS continuity_agent.agent_execution_log
(
    execution_id  UUID,
    agent_name    LowCardinality(String),
    scene_id      String,
    take_id       String,
    step_number   UInt32,
    step_type     Enum8(
                      'reasoning'       = 1,
                      'tool_call'       = 2,
                      'tool_result'     = 3,
                      'anomaly_flagged' = 4,
                      'final_report'    = 5,
                      'error'           = 6
                  ),
    tool_name     String DEFAULT '',
    input_payload String DEFAULT '',   -- JSON string
    output_payload String DEFAULT '',  -- JSON string
    latency_ms    UInt32 DEFAULT 0,
    started_at    DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
ORDER BY (execution_id, step_number);

-- Ingestion job bookkeeping so the dashboard can show upload/processing
-- status without polling the filesystem.
CREATE TABLE IF NOT EXISTS continuity_agent.ingestion_jobs
(
    job_id            UUID,
    scene_id          String,
    take_id           String,
    source_filename   String,
    storage_key       String DEFAULT '',  -- backend-agnostic location; see app/services/object_storage.py
    status            Enum8('pending' = 1, 'extracting_frames' = 2, 'analyzing' = 3,
                             'completed' = 4, 'failed' = 5),
    total_frames      UInt32 DEFAULT 0,
    processed_frames  UInt32 DEFAULT 0,
    error_message     String DEFAULT '',
    created_at        DateTime DEFAULT now(),
    updated_at        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (job_id);
