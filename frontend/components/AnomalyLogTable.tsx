"use client";

import { Check } from "lucide-react";
import { useState } from "react";

import { SeverityBadge } from "@/components/SeverityBadge";
import { resolveAnomaly } from "@/lib/api";
import type { ContinuityAnomaly } from "@/lib/types";
import { formatRelativeTime, truncate } from "@/lib/utils";

const ANOMALY_TYPE_LABEL: Record<ContinuityAnomaly["anomaly_type"], string> = {
  prop_mismatch: "Prop",
  wardrobe_mismatch: "Wardrobe",
  position_mismatch: "Position",
  lighting_mismatch: "Lighting",
  continuity_other: "Other",
};

interface AnomalyLogTableProps {
  anomalies: ContinuityAnomaly[];
  onSelect?: (anomaly: ContinuityAnomaly) => void;
  onResolved?: (anomalyId: string) => void;
}

export function AnomalyLogTable({ anomalies, onSelect, onResolved }: AnomalyLogTableProps) {
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  async function handleResolve(anomaly: ContinuityAnomaly) {
    if (!anomaly.anomaly_id) return;
    setResolvingId(anomaly.anomaly_id);
    try {
      await resolveAnomaly(anomaly.anomaly_id, "Reviewed and cleared from dashboard.");
      onResolved?.(anomaly.anomaly_id);
    } finally {
      setResolvingId(null);
    }
  }

  if (anomalies.length === 0) {
    return (
      <div className="rounded-sm border border-stage-700 bg-stage-900 p-6 text-center">
        <p className="text-sm text-stage-400">No continuity anomalies recorded for this take.</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-sm border border-stage-700">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-stage-700 bg-stage-900 text-left text-xs uppercase tracking-wider text-stage-400">
            <th className="px-3 py-2 font-medium">Severity</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-mono font-medium">Timecode</th>
            <th className="px-3 py-2 font-medium">Description</th>
            <th className="px-3 py-2 font-medium">Detected</th>
            <th className="px-3 py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {anomalies.map((anomaly) => (
            <tr
              key={anomaly.anomaly_id}
              className="cursor-pointer border-b border-stage-800 bg-stage-950 transition hover:bg-stage-900"
              onClick={() => onSelect?.(anomaly)}
            >
              <td className="px-3 py-2.5">
                <SeverityBadge severity={anomaly.severity} />
              </td>
              <td className="px-3 py-2.5 text-stage-300">{ANOMALY_TYPE_LABEL[anomaly.anomaly_type]}</td>
              <td className="px-3 py-2.5 font-mono text-xs text-stage-300 tabular-nums">
                {anomaly.timecode_b || anomaly.timecode_a}
              </td>
              <td className="px-3 py-2.5 text-stage-100">{truncate(anomaly.description, 90)}</td>
              <td className="px-3 py-2.5 text-xs text-stage-400">
                {formatRelativeTime(anomaly.detected_at)}
              </td>
              <td className="px-3 py-2.5 text-right">
                {anomaly.resolved ? (
                  <span className="text-xs text-flag-resolved">Resolved</span>
                ) : (
                  <button
                    type="button"
                    disabled={resolvingId === anomaly.anomaly_id}
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleResolve(anomaly);
                    }}
                    className="inline-flex items-center gap-1 rounded-sm border border-stage-600 px-2 py-1 text-xs text-stage-300 transition hover:border-flag-resolved hover:text-flag-resolved disabled:opacity-50"
                  >
                    <Check size={12} />
                    Resolve
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
