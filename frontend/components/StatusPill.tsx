import { cn } from "@/lib/utils";

type Tone = "neutral" | "active" | "success" | "error";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "text-stage-300 bg-stage-700/60",
  active: "text-agent-accent bg-agent-accent/10",
  success: "text-flag-resolved bg-flag-resolved/10",
  error: "text-flag-critical bg-flag-critical/10",
};

export function StatusPill({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-wider",
        TONE_CLASSES[tone],
      )}
    >
      {label}
    </span>
  );
}
