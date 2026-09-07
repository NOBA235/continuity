"use client";

import { Clapperboard, Loader2 } from "lucide-react";
import { useState } from "react";

import { login, registerFirstAccount } from "@/lib/auth";

interface LoginScreenProps {
  onAuthenticated: () => void;
}

type Mode = "login" | "bootstrap";

export function LoginScreen({ onAuthenticated }: LoginScreenProps) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await registerFirstAccount(email, password, displayName);
      }
      onAuthenticated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-2 text-center">
          <Clapperboard size={28} className="text-stage-300" />
          <h1 className="font-[family-name:var(--font-display)] text-xl text-stage-100">
            Continuity.Agent
          </h1>
          <p className="text-sm text-stage-400">Script Supervisor &amp; Visual Continuity QA</p>
        </div>

        <div className="mb-5 flex gap-1 border-b border-stage-700">
          <button
            type="button"
            onClick={() => {
              setMode("login");
              setError(null);
            }}
            className={`px-3 py-2 text-sm font-medium transition ${
              mode === "login"
                ? "border-b-2 border-stage-100 text-stage-100"
                : "text-stage-400 hover:text-stage-200"
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("bootstrap");
              setError(null);
            }}
            className={`px-3 py-2 text-sm font-medium transition ${
              mode === "bootstrap"
                ? "border-b-2 border-stage-100 text-stage-100"
                : "text-stage-400 hover:text-stage-200"
            }`}
          >
            First-time setup
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          {mode === "bootstrap" && (
            <div>
              <label className="mb-1 block text-xs uppercase tracking-wider text-stage-400" htmlFor="name">
                Your name
              </label>
              <input
                id="name"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full rounded-sm border border-stage-600 bg-stage-800 px-3 py-2 text-sm text-stage-100"
                placeholder="Alex Rivera"
              />
            </div>
          )}

          <div>
            <label className="mb-1 block text-xs uppercase tracking-wider text-stage-400" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-sm border border-stage-600 bg-stage-800 px-3 py-2 text-sm text-stage-100"
              placeholder="you@studio.com"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs uppercase tracking-wider text-stage-400" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-sm border border-stage-600 bg-stage-800 px-3 py-2 text-sm text-stage-100"
              placeholder="••••••••"
            />
          </div>

          {mode === "bootstrap" && (
            <p className="text-xs text-stage-500">
              This only works once, for the very first account on a fresh deployment. It's
              automatically granted the supervisor role so you can invite everyone else.
            </p>
          )}

          {error && <p className="text-sm text-flag-critical">{error}</p>}

          <button
            type="submit"
            disabled={isSubmitting}
            className="mt-2 inline-flex items-center justify-center gap-2 rounded-sm bg-agent-accent/15 px-3 py-2 text-sm font-medium text-agent-accent transition hover:bg-agent-accent/25 disabled:opacity-50"
          >
            {isSubmitting && <Loader2 size={14} className="animate-spin" />}
            {mode === "login" ? "Sign in" : "Create supervisor account"}
          </button>
        </form>
      </div>
    </main>
  );
}
