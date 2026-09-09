import type { UserRole } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
const STORAGE_KEY = "continuity_agent_tokens";
export const AUTH_REQUIRED_EVENT = "continuity-auth-required";

export interface StoredTokens {
  access_token: string;
  refresh_token: string;
}

export interface CurrentUser {
  user_id: string;
  email: string;
  display_name: string;
  role: UserRole;
  created_at: string;
}

export class AuthRequiredError extends Error {
  constructor() {
    super("Authentication required");
    this.name = "AuthRequiredError";
  }
}

export function getStoredTokens(): StoredTokens | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredTokens;
  } catch {
    return null;
  }
}

function storeTokens(tokens: StoredTokens): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
}

export function clearTokens(): void {
  window.localStorage.removeItem(STORAGE_KEY);
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body?.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

export async function login(email: string, password: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error(await parseErrorDetail(response));
  const tokens = (await response.json()) as StoredTokens;
  storeTokens(tokens);
}

/**
 * Registers a public viewer account. The backend promotes only the very
 * first account to supervisor; submitted role values are ignored here.
 */
export async function registerAccount(
  email: string,
  password: string,
  displayName: string,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  if (!response.ok) throw new Error(await parseErrorDetail(response));
  // Registration doesn't return tokens -- log in immediately after.
  await login(email, password);
}

export function logout(): void {
  clearTokens();
}

// Prevents a burst of concurrent 401s from each firing their own refresh
// call -- they all await the same in-flight promise instead.
let refreshInFlight: Promise<StoredTokens> | null = null;

async function refreshTokens(): Promise<StoredTokens> {
  const current = getStoredTokens();
  if (!current) throw new AuthRequiredError();

  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: current.refresh_token }),
    })
      .then(async (response) => {
        if (!response.ok) {
          clearTokens();
          throw new AuthRequiredError();
        }
        const tokens = (await response.json()) as StoredTokens;
        storeTokens(tokens);
        return tokens;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

/**
 * Fetch wrapper used by every authenticated API call (see lib/api.ts).
 * Attaches the current access token; on a 401, refreshes once and retries
 * the request exactly one time before giving up.
 */
export async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  let tokens = getStoredTokens();
  if (!tokens) throw new AuthRequiredError();

  const doFetch = (accessToken: string) =>
    fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...init?.headers,
        Authorization: `Bearer ${accessToken}`,
      },
    });

  let response = await doFetch(tokens.access_token);
  if (response.status === 401 || response.status === 403) {
    try {
      tokens = await refreshTokens();
    } catch {
      clearTokens();
      window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
      throw new AuthRequiredError();
    }
    response = await doFetch(tokens.access_token);
  }
  return response;
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const response = await authFetch("/api/auth/me");
  if (!response.ok) throw new AuthRequiredError();
  return (await response.json()) as CurrentUser;
}
