"use client";

import { Pause, Play, Volume2, VolumeX } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ContinuityAnomaly } from "@/lib/types";
import { SEVERITY_COLOR, cn, timecodeToSeconds } from "@/lib/utils";

interface VideoPlayerProps {
  videoUrl: string | null;
  anomalies: ContinuityAnomaly[];
  onSeekToAnomaly?: (anomaly: ContinuityAnomaly) => void;
}

function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds)) return "00:00";
  const mm = Math.floor(seconds / 60);
  const ss = Math.floor(seconds % 60);
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

export function VideoPlayer({ videoUrl, anomalies, onSeekToAnomaly }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
  }, [videoUrl]);

  const markers = useMemo(
    () =>
      anomalies
        .map((anomaly) => ({
          anomaly,
          seconds: timecodeToSeconds(anomaly.timecode_b || anomaly.timecode_a),
        }))
        .filter((m) => duration > 0 && m.seconds <= duration),
    [anomalies, duration],
  );

  function togglePlay() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play();
      setIsPlaying(true);
    } else {
      video.pause();
      setIsPlaying(false);
    }
  }

  function toggleMute() {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setIsMuted(video.muted);
  }

  function seekTo(seconds: number) {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = seconds;
    setCurrentTime(seconds);
  }

  if (!videoUrl) {
    return (
      <div className="flex aspect-video w-full items-center justify-center rounded-sm border border-stage-700 bg-stage-900">
        <p className="font-mono text-sm text-stage-400">No dailies loaded for this take yet.</p>
      </div>
    );
  }

  return (
    <div className="w-full">
      <div className="relative aspect-video w-full overflow-hidden rounded-sm border border-stage-700 bg-black">
        <video
          ref={videoRef}
          src={videoUrl}
          muted={isMuted}
          className="h-full w-full"
          onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onClick={togglePlay}
        />
      </div>

      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          onClick={togglePlay}
          className="flex h-8 w-8 items-center justify-center rounded-sm bg-stage-800 text-stage-100 transition hover:bg-stage-700"
          aria-label={isPlaying ? "Pause" : "Play"}
        >
          {isPlaying ? <Pause size={16} /> : <Play size={16} />}
        </button>

        <span className="font-mono text-xs text-stage-300 tabular-nums">
          {formatClock(currentTime)} / {formatClock(duration)}
        </span>

        <div className="relative flex-1">
          <input
            type="range"
            className="scrub-range w-full"
            min={0}
            max={duration || 0}
            step={0.01}
            value={currentTime}
            onChange={(e) => seekTo(Number(e.target.value))}
            aria-label="Seek"
          />
          {/* Flag rail: one tick per continuity anomaly, positioned by timecode */}
          <div className="pointer-events-none absolute inset-x-0 top-full mt-1 h-2">
            {markers.map(({ anomaly, seconds }) => (
              <button
                key={anomaly.anomaly_id ?? `${anomaly.frame_number_a}-${anomaly.frame_number_b}`}
                type="button"
                title={anomaly.description}
                className="pointer-events-auto absolute h-2 w-[3px] -translate-x-1/2 cursor-pointer rounded-full transition hover:scale-y-150"
                style={{
                  left: `${(seconds / duration) * 100}%`,
                  backgroundColor: SEVERITY_COLOR[anomaly.severity],
                }}
                onClick={() => {
                  seekTo(seconds);
                  onSeekToAnomaly?.(anomaly);
                }}
              />
            ))}
          </div>
        </div>

        <button
          type="button"
          onClick={toggleMute}
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-sm text-stage-100 transition hover:bg-stage-700",
            isMuted ? "bg-stage-800" : "bg-stage-800",
          )}
          aria-label={isMuted ? "Unmute" : "Mute"}
        >
          {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </button>
      </div>
    </div>
  );
}
