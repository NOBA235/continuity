import { authFetch, getStoredTokens } from "./auth";
import type {
  AgentExecutionStep,
  AgentRunResponse,
  ContinuityAnomaly,
  FrameMetadataRecord,
  IngestionJob,
  Severity,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await authFetch(path, init);
  } catch {
    // AuthRequiredError from authFetch (no/expired session) bubbles up as
    // this -- app/page.tsx catches it to fall back to the login screen.
    throw new ApiError(401, "Unauthorized", "Your session has expired. Please sign in again.");
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // response body wasn't JSON -- fall back to statusText
    }
    throw new ApiError(response.status, response.statusText, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// --- Frames -----------------------------------------------------------
export const listScenes = () => request<string[]>("/api/frames/scenes");

export const listTakes = (sceneId: string) =>
  request<string[]>(`/api/frames/scenes/${encodeURIComponent(sceneId)}/takes`);

export const listFrames = (sceneId: string, takeId: string) =>
  request<FrameMetadataRecord[]>(
    `/api/frames?scene_id=${encodeURIComponent(sceneId)}&take_id=${encodeURIComponent(takeId)}`,
  );

// --- Anomalies ----------------------------------------------------------
export const listAnomalies = (params: {
  sceneId?: string;
  takeId?: string;
  resolved?: boolean;
  minSeverity?: Severity;
}) => {
  const search = new URLSearchParams();
  if (params.sceneId) search.set("scene_id", params.sceneId);
  if (params.takeId) search.set("take_id", params.takeId);
  if (params.resolved !== undefined) search.set("resolved", String(params.resolved));
  if (params.minSeverity) search.set("min_severity", params.minSeverity);
  return request<ContinuityAnomaly[]>(`/api/anomalies?${search.toString()}`);
};

export const resolveAnomaly = (anomalyId: string, resolvedNote: string) =>
  request<void>(`/api/anomalies/${anomalyId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ resolved_note: resolvedNote }),
  });

// --- Agent ----------------------------------------------------------------
export const triggerContinuityCheck = (
  sceneId: string,
  takeId: string,
  compareAgainstTakeId?: string,
) =>
  request<AgentRunResponse>("/api/agent/run", {
    method: "POST",
    body: JSON.stringify({
      scene_id: sceneId,
      take_id: takeId,
      compare_against_take_id: compareAgainstTakeId ?? null,
    }),
  });

export const getExecutionTrace = (executionId: string) =>
  request<AgentExecutionStep[]>(`/api/agent/executions/${executionId}`);

// --- Ingestion --------------------------------------------------------
export const uploadDailies = (sceneId: string, takeId: string, file: File) => {
  const formData = new FormData();
  formData.append("scene_id", sceneId);
  formData.append("take_id", takeId);
  formData.append("file", file);
  return request<{ job_id: string; scene_id: string; take_id: string }>("/api/ingestion/upload", {
    method: "POST",
    body: formData,
  });
};

export const getJobStatus = (jobId: string) => request<IngestionJob>(`/api/ingestion/jobs/${jobId}`);

export const listJobsForScene = (sceneId: string) =>
  request<IngestionJob[]>(`/api/ingestion/jobs?scene_id=${encodeURIComponent(sceneId)}`);

/** Direct <video src> URL -- the backend streams this with HTTP range support.
 * Uses ?access_token= rather than an Authorization header because a <video>
 * element fetches its src directly; it can't attach custom headers. */
export const videoStreamUrl = (jobId: string): string => {
  const tokens = getStoredTokens();
  const base = `${API_BASE_URL}/api/ingestion/jobs/${jobId}/video`;
  return tokens ? `${base}?access_token=${encodeURIComponent(tokens.access_token)}` : base;
};
