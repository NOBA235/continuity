"use client";

import { AlertTriangle, Flag, MessageSquare, Terminal, Wrench } from "lucide-react";

import type { AgentExecutionStep, AgentStepType } from "@/lib/types";
import { STEP_TYPE_LABEL, cn } from "@/lib/utils";

const STEP_ICON: Record<AgentStepType, React.ComponentType<{ size?: number }>> = {
  reasoning: MessageSquare,
  tool_call: Terminal,
  tool_result: Wrench,
  anomaly_flagged: Flag,
  final_report: MessageSquare,
  error: AlertTriangle,
};

function stepAccentClass(stepType: AgentStepType): string {
  switch (stepType) {
    case "anomaly_flagged":
      return "text-flag-high border-flag-high/40";
    case "error":
      return "text-flag-critical border-flag-critical/40";
    case "final_report":
      return "text-flag-resolved border-flag-resolved/40";
    default:
      return "text-agent-accent border-agent-accent/30";
  }
}

interface AgentTraceLogProps {
  steps: AgentExecutionStep[];
  isRunning?: boolean;
}

export function AgentTraceLog({ steps, isRunning }: AgentTraceLogProps) {
  if (steps.length === 0) {
    return (
      <div className="rounded-sm border border-stage-700 bg-stage-900 p-6 text-center">
        <p className="text-sm text-stage-400">
          {isRunning ? "Agent run starting\u2026" : "No agent runs yet for this take."}
        </p>
      </div>
    );
  }

  return (
    <ol className="space-y-0">
      {steps.map((step, index) => {
        const Icon = STEP_ICON[step.step_type];
        const isLast = index === steps.length - 1;
        return (
          <li key={`${step.execution_id}-${step.step_number}`} className="relative flex gap-3 pb-4">
            {!isLast && (
              <span className="absolute left-[15px] top-8 h-full w-px bg-stage-700" aria-hidden />
            )}
            <span
              className={cn(
                "z-10 flex h-8 w-8 flex-none items-center justify-center rounded-full border bg-stage-950",
                stepAccentClass(step.step_type),
              )}
            >
              <Icon size={14} />
            </span>
            <div className="min-w-0 flex-1 pt-1">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-xs font-medium uppercase tracking-wider text-stage-400">
                  {STEP_TYPE_LABEL[step.step_type]}
                </span>
                {step.tool_name && (
                  <span className="font-mono text-xs text-stage-300">{step.tool_name}</span>
                )}
                <span className="font-mono text-[11px] text-stage-500">{step.latency_ms}ms</span>
              </div>
              {step.output_payload && (
                <p className="mt-1 whitespace-pre-wrap break-words text-sm text-stage-100">
                  {step.output_payload.length > 400
                    ? `${step.output_payload.slice(0, 400)}\u2026`
                    : step.output_payload}
                </p>
              )}
              {step.input_payload && (
                <p className="mt-1 truncate font-mono text-xs text-stage-500">{step.input_payload}</p>
              )}
            </div>
          </li>
        );
      })}
      {isRunning && (
        <li className="flex items-center gap-3 pt-1 text-xs text-agent-accent">
          <span className="h-2 w-2 animate-pulse rounded-full bg-agent-accent" />
          Agent is still working…
        </li>
      )}
    </ol>
  );
}
