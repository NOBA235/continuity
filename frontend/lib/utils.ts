import { clsx, type ClassValue } from "clsx";
import type { AgentStepType, Severity } from "./types";

export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}

export const SEVERITY_COLOR: Record<Severity, string> = {
  low: "var(--color-flag-low)",
  medium: "var(--color-flag-medium)",
  high: "var(--color-flag-high)",
  critical: "var(--color-flag-critical)",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export const STEP_TYPE_LABEL: Record<AgentStepType, string> = {
  reasoning: "Reasoning",
  tool_call: "Tool call",
  tool_result: "Tool result",
  anomaly_flagged: "Anomaly flagged",
  final_report: "Final report",
  error: "Error",
};

/** Parse an SMPTE "HH:MM:SS:FF" timecode into total seconds for scrub-bar math. */
export function timecodeToSeconds(timecode: string, fps = 24): number {
  const parts = timecode.split(":").map(Number);
  if (parts.length !== 4 || parts.some(Number.isNaN)) return 0;
  const [hh, mm, ss, ff] = parts as [number, number, number, number];
  return hh * 3600 + mm * 60 + ss + ff / fps;
}

export function formatRelativeTime(isoString: string | null): string {
  if (!isoString) return "--";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "--";
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return date.toLocaleDateString();
}

export function truncate(text: string, maxLength: number): string {
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}\u2026` : text;
}
