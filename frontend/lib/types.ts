// Mirrors backend/app/models/schemas.py. Keep in sync manually -- there is
// no shared codegen step in this project, so a field renamed on one side
// without the other will surface as a TypeScript error here, which is the
// point: it's cheaper to catch at compile time than at render time.

export type AnomalyType =
  | "prop_mismatch"
  | "wardrobe_mismatch"
  | "position_mismatch"
  | "lighting_mismatch"
  | "continuity_other";

export type Severity = "low" | "medium" | "high" | "critical";

export interface ContinuityAnomaly {
  anomaly_id: string | null;
  scene_id: string;
  take_id: string;
  compared_take_id: string;
  frame_number_a: number;
  frame_number_b: number;
  timecode_a: string;
  timecode_b: string;
  anomaly_type: AnomalyType;
  description: string;
  severity: Severity;
  detected_by_agent: string;
  confidence_score: number;
  resolved: boolean;
  resolved_note: string;
  detected_at: string | null;
}

export interface FrameMetadataRecord {
  scene_id: string;
  take_id: string;
  video_id: string;
  timecode: string;
  frame_number: number;
  timestamp: string;
  actor_id: string;
  wardrobe_description: string;
  prop_list: string[];
  prop_states: string;
  lighting_vector: number[];
  confidence_score: number;
  gemini_model: string;
}

export type AgentStepType =
  | "reasoning"
  | "tool_call"
  | "tool_result"
  | "anomaly_flagged"
  | "final_report"
  | "error";

export interface AgentExecutionStep {
  execution_id: string;
  agent_name: string;
  scene_id: string;
  take_id: string;
  step_number: number;
  step_type: AgentStepType;
  tool_name: string;
  input_payload: string;
  output_payload: string;
  latency_ms: number;
  started_at: string;
}

export type IngestionStatus =
  | "pending"
  | "extracting_frames"
  | "analyzing"
  | "completed"
  | "failed";

export interface IngestionJob {
  job_id: string;
  scene_id: string;
  take_id: string;
  source_filename: string;
  status: IngestionStatus;
  total_frames: number;
  processed_frames: number;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface AgentRunResponse {
  execution_id: string;
  status: string;
}

export type UserRole = "viewer" | "editor" | "supervisor";
