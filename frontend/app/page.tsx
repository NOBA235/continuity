"use client";

import { Clapperboard, LogOut } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { AgentTraceLog } from "@/components/AgentTraceLog";
import { AnomalyLogTable } from "@/components/AnomalyLogTable";
import { LoginScreen } from "@/components/LoginScreen";
import { SceneTakeBar } from "@/components/SceneTakeBar";
import { StatusPill } from "@/components/StatusPill";
import { VideoPlayer } from "@/components/VideoPlayer";
import {
  ApiError,
  getExecutionTrace,
  getJobStatus,
  listAnomalies,
  listJobsForScene,
  listScenes,
  listTakes,
  triggerContinuityCheck,
  videoStreamUrl,
} from "@/lib/api";
import { fetchCurrentUser, getStoredTokens, logout, type CurrentUser } from "@/lib/auth";
import type { AgentExecutionStep, ContinuityAnomaly, IngestionJob } from "@/lib/types";

type Tab = "log" | "trace";
type AuthState = "checking" | "authenticated" | "unauthenticated";

const POLL_INTERVAL_MS = 2500;

export default function Page() {
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);

  const checkSession = useCallback(() => {
    if (!getStoredTokens()) {
      setAuthState("unauthenticated");
      return;
    }
    fetchCurrentUser()
      .then((user) => {
        setCurrentUser(user);
        setAuthState("authenticated");
      })
      .catch(() => {
        logout();
        setAuthState("unauthenticated");
      });
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  function handleLogout() {
    logout();
    setCurrentUser(null);
    setAuthState("unauthenticated");
  }

  if (authState === "checking") {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-stage-500">Loading…</p>
      </main>
    );
  }

  if (authState === "unauthenticated" || !currentUser) {
    return <LoginScreen onAuthenticated={checkSession} />;
  }

  return <Dashboard currentUser={currentUser} onLogout={handleLogout} />;
}

function Dashboard({ currentUser, onLogout }: { currentUser: CurrentUser; onLogout: () => void }) {
  const [scenes, setScenes] = useState<string[]>([]);
  const [takes, setTakes] = useState<string[]>([]);
  const [selectedScene, setSelectedScene] = useState<string | null>(null);
  const [selectedTake, setSelectedTake] = useState<string | null>(null);

  const [videoJob, setVideoJob] = useState<IngestionJob | null>(null);
  const [anomalies, setAnomalies] = useState<ContinuityAnomaly[]>([]);
  const [activeTab, setActiveTab] = useState<Tab>("log");

  const [executionId, setExecutionId] = useState<string | null>(null);
  const [executionSteps, setExecutionSteps] = useState<AgentExecutionStep[]>([]);
  const [isAgentRunning, setIsAgentRunning] = useState(false);
  const [tracePollAttempts, setTracePollAttempts] = useState(0);

  const [loadError, setLoadError] = useState<string | null>(null);

  // Load scenes once on mount.
  useEffect(() => {
    listScenes()
      .then(setScenes)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Failed to load scenes."));
  }, []);

  // Load takes whenever the scene changes.
  useEffect(() => {
    if (!selectedScene) {
      setTakes([]);
      return;
    }
    listTakes(selectedScene).then(setTakes).catch(() => setTakes([]));
  }, [selectedScene]);

  const refreshAnomalies = useCallback(() => {
    if (!selectedScene || !selectedTake) return;
    listAnomalies({ sceneId: selectedScene, takeId: selectedTake })
      .then(setAnomalies)
      .catch(() => setAnomalies([]));
  }, [selectedScene, selectedTake]);

  const refreshVideoJob = useCallback(() => {
    if (!selectedScene || !selectedTake) return;
    listJobsForScene(selectedScene)
      .then((jobs) => {
        const match = jobs.find((j) => j.take_id === selectedTake) ?? null;
        setVideoJob(match);
      })
      .catch(() => setVideoJob(null));
  }, [selectedScene, selectedTake]);

  // Reload anomalies + the video job whenever scene/take changes.
  useEffect(() => {
    refreshAnomalies();
    refreshVideoJob();
    setExecutionId(null);
    setExecutionSteps([]);
  }, [refreshAnomalies, refreshVideoJob]);

  // Poll ingestion job status while a job is in flight.
  useEffect(() => {
    if (!videoJob || videoJob.status === "completed" || videoJob.status === "failed") return;
    const interval = setInterval(() => {
      getJobStatus(videoJob.job_id)
        .then(setVideoJob)
        .catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [videoJob]);

  // Poll the agent's execution trace while a run is in flight.
  useEffect(() => {
    if (!executionId) return;
    setIsAgentRunning(true);
    setTracePollAttempts(0);
    const interval = setInterval(() => {
      getExecutionTrace(executionId)
        .then((steps) => {
          setExecutionSteps(steps);
          const finished = steps.some(
            (s) => s.step_type === "final_report" || s.step_type === "error",
          );
          if (finished) {
            setIsAgentRunning(false);
            refreshAnomalies();
            clearInterval(interval);
          }
        })
        .catch((err) => {
          if (err instanceof ApiError && err.status === 404) {
            setTracePollAttempts((attempts) => {
              const nextAttempts = attempts + 1;
              if (nextAttempts >= 12) {
                setIsAgentRunning(false);
                setLoadError("The continuity check did not produce a trace. Check the backend logs.");
                clearInterval(interval);
              }
              return nextAttempts;
            });
            return;
          }
          setIsAgentRunning(false);
          clearInterval(interval);
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [executionId, refreshAnomalies]);

  async function handleRunAgent() {
    if (!selectedScene || !selectedTake) return;
    setActiveTab("trace");
    setExecutionSteps([]);
    try {
      const { execution_id } = await triggerContinuityCheck(selectedScene, selectedTake);
      setExecutionId(execution_id);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to start agent run.");
    }
  }

  function handleUploaded(jobId: string) {
    if (!selectedScene || !selectedTake) return;
    setVideoJob({
      job_id: jobId,
      scene_id: selectedScene,
      take_id: selectedTake,
      source_filename: "",
      status: "pending",
      total_frames: 0,
      processed_frames: 0,
      error_message: "",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }

  const videoUrl = videoJob ? videoStreamUrl(videoJob.job_id) : null;

  return (
    <main className="min-h-screen">
      <header className="flex items-center gap-3 border-b border-stage-700 px-4 py-3">
        <Clapperboard size={20} className="text-stage-300" />
        <h1 className="font-[family-name:var(--font-display)] text-lg tracking-tight text-stage-100">
          Continuity.Agent
        </h1>
        <span className="text-xs text-stage-500">Script Supervisor &amp; Visual Continuity QA</span>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-stage-400">
            {currentUser.email} <span className="text-stage-600">·</span> {currentUser.role}
          </span>
          <button
            type="button"
            onClick={onLogout}
            className="flex items-center gap-1.5 rounded-sm border border-stage-600 px-2 py-1 text-xs text-stage-300 transition hover:border-stage-400 hover:text-stage-100"
          >
            <LogOut size={12} />
            Sign out
          </button>
        </div>
      </header>

      <SceneTakeBar
        scenes={scenes}
        takes={takes}
        selectedScene={selectedScene}
        selectedTake={selectedTake}
        onSelectScene={(scene) => {
          setSelectedScene(scene);
          setSelectedTake(null);
        }}
        onSelectTake={setSelectedTake}
        onUploaded={handleUploaded}
        onRunAgent={handleRunAgent}
        isAgentRunning={isAgentRunning}
        canEdit={currentUser.role !== "viewer"}
      />

      {loadError && (
        <div className="border-b border-flag-critical/30 bg-flag-critical/10 px-4 py-2 text-sm text-flag-critical">
          {loadError}
        </div>
      )}

      {!selectedScene || !selectedTake ? (
        <div className="flex flex-col items-center justify-center gap-2 px-4 py-24 text-center">
          <p className="text-stage-300">Select a scene and take to begin reviewing dailies.</p>
          <p className="text-sm text-stage-500">
            No scenes indexed yet? Pick any scene/take id and upload a video to start ingestion.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 p-4 lg:grid-cols-[1.4fr_1fr]">
          <section>
            {videoJob && videoJob.status !== "completed" && videoJob.status !== "failed" && (
              <div className="mb-3 flex items-center gap-2">
                <StatusPill label={videoJob.status.replace("_", " ")} tone="active" />
                <span className="font-mono text-xs text-stage-400">
                  {videoJob.processed_frames}/{videoJob.total_frames || "?"} frames analyzed
                </span>
              </div>
            )}
            {videoJob?.status === "failed" && (
              <div className="mb-3">
                <StatusPill label="Ingestion failed" tone="error" />
                <p className="mt-1 text-xs text-flag-critical">{videoJob.error_message}</p>
              </div>
            )}
            <VideoPlayer videoUrl={videoUrl} anomalies={anomalies} />
          </section>

          <section className="min-w-0">
            <div className="mb-3 flex gap-1 border-b border-stage-700">
              <button
                type="button"
                onClick={() => setActiveTab("log")}
                className={`px-3 py-2 text-sm font-medium transition ${
                  activeTab === "log"
                    ? "border-b-2 border-stage-100 text-stage-100"
                    : "text-stage-400 hover:text-stage-200"
                }`}
              >
                Continuity Log ({anomalies.length})
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("trace")}
                className={`px-3 py-2 text-sm font-medium transition ${
                  activeTab === "trace"
                    ? "border-b-2 border-stage-100 text-stage-100"
                    : "text-stage-400 hover:text-stage-200"
                }`}
              >
                Agent Trace
              </button>
            </div>

            {activeTab === "log" ? (
              <AnomalyLogTable anomalies={anomalies} onResolved={refreshAnomalies} />
            ) : (
              <AgentTraceLog steps={executionSteps} isRunning={isAgentRunning} />
            )}
          </section>
        </div>
      )}
    </main>
  );
}
