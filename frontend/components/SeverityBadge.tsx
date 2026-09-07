import { SEVERITY_COLOR, SEVERITY_LABEL } from "@/lib/utils";
import type { Severity } from "@/lib/types";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-xs font-medium tracking-wide"
      style={{
        color: SEVERITY_COLOR[severity],
        backgroundColor: `color-mix(in srgb, ${SEVERITY_COLOR[severity]} 16%, transparent)`,
      }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: SEVERITY_COLOR[severity] }}
        aria-hidden
      />
      {SEVERITY_LABEL[severity]}
    </span>
  );
}
