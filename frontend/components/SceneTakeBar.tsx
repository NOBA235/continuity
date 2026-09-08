"use client";

import { Loader2, Play, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { uploadDailies } from "@/lib/api";
import { cn } from "@/lib/utils";

interface SceneTakeBarProps {
  scenes: string[];
  takes: string[];
  selectedScene: string | null;
  selectedTake: string | null;
  onSelectScene: (sceneId: string) => void;
  onSelectTake: (takeId: string) => void;
  onUploaded: (jobId: string) => void;
  onRunAgent: () => void;
  isAgentRunning: boolean;
  canRunAgent: boolean;
  canEdit: boolean;
}

export function SceneTakeBar({
  scenes,
  takes,
  selectedScene,
  selectedTake,
  onSelectScene,
  onSelectTake,
  onUploaded,
  onRunAgent,
  isAgentRunning,
  canRunAgent,
  canEdit,
}: SceneTakeBarProps) {
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleFileChosen(file: File) {
    if (!selectedScene || !selectedTake) {
      setUploadError("Choose a scene and take before uploading.");
      return;
    }
    setIsUploading(true);
    setUploadError(null);
    try {
      const { job_id } = await uploadDailies(selectedScene, selectedTake, file);
      onUploaded(job_id);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-stage-700 bg-stage-900 px-4 py-3">
      <div className="flex items-center gap-2">
        <label className="text-xs uppercase tracking-wider text-stage-400" htmlFor="scene-select">
          Scene
        </label>
        <input
          id="scene-select"
          list="scene-options"
          value={selectedScene ?? ""}
          onChange={(e) => onSelectScene(e.target.value)}
          placeholder="Enter scene"
          className="w-36 rounded-sm border border-stage-600 bg-stage-800 px-2 py-1 text-sm text-stage-100 placeholder:text-stage-500"
        />
        <datalist id="scene-options">
          {scenes.map((scene) => (
            <option key={scene} value={scene} />
          ))}
        </datalist>
      </div>

      <div className="flex items-center gap-2">
        <label className="text-xs uppercase tracking-wider text-stage-400" htmlFor="take-select">
          Take
        </label>
        <input
          id="take-select"
          list="take-options"
          value={selectedTake ?? ""}
          onChange={(e) => onSelectTake(e.target.value)}
          disabled={!selectedScene}
          placeholder="Enter take"
          className="w-36 rounded-sm border border-stage-600 bg-stage-800 px-2 py-1 text-sm text-stage-100 placeholder:text-stage-500 disabled:opacity-50"
        />
        <datalist id="take-options">
          {takes.map((take) => (
            <option key={take} value={take} />
          ))}
        </datalist>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {uploadError && <span className="text-xs text-flag-critical">{uploadError}</span>}
        <input
          ref={fileInputRef}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFileChosen(file);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading || !selectedScene || !selectedTake || !canEdit}
          title={canEdit ? undefined : "Viewers can't upload dailies"}
          className="inline-flex items-center gap-2 rounded-sm border border-stage-600 px-3 py-1.5 text-sm text-stage-100 transition hover:border-stage-400 disabled:opacity-50"
        >
          {isUploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          Upload dailies
        </button>

        <button
          type="button"
          onClick={onRunAgent}
          disabled={isAgentRunning || !selectedScene || !selectedTake || !canEdit || !canRunAgent}
          title={
            !canEdit
              ? "Viewers can't run the continuity agent"
              : !canRunAgent
                ? "Wait for dailies ingestion to complete before running the continuity check"
                : undefined
          }
          className={cn(
            "inline-flex items-center gap-2 rounded-sm px-3 py-1.5 text-sm font-medium transition",
            "bg-agent-accent/15 text-agent-accent hover:bg-agent-accent/25 disabled:opacity-50",
          )}
        >
          {isAgentRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          Run continuity check
        </button>
      </div>
    </div>
  );
}
