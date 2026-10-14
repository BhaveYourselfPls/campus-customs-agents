import type {
  ActionsResponse,
  AgentAction,
  Cash,
  RunResult,
  TicketsResponse,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/** Throw the backend's own error detail rather than a generic status code.
 *  The API refuses things for specific, readable reasons (agent-named
 *  approver, overdraw, unknown resolution) and the operator needs to see which. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json())?.detail;
    } catch {
      detail = await res.text();
    }
    const message =
      typeof detail === "string"
        ? detail
        : (detail as { error?: string })?.error ??
          JSON.stringify(detail ?? res.statusText);
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; model: string }>("/health"),

  tickets: () => request<TicketsResponse>("/tickets"),

  runTeam: (ticketId: string) =>
    request<RunResult>(`/tickets/${ticketId}/run`, {
      method: "POST",
      body: JSON.stringify({}),
    }),

  resolve: (
    ticketId: string,
    body: { decision: string; rationale: string; resolved_by: string },
  ) =>
    request<{ recorded: boolean; status: string }>(
      `/tickets/${ticketId}/resolve`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  history: (ticketId: string) =>
    request<{
      ticket_id: string;
      run_id: string | null;
      run_count?: number;
      actions: AgentAction[];
      agents_involved?: string[];
    }>(`/tickets/${ticketId}/history`),

  actions: (limit = 60, runId?: string) =>
    request<ActionsResponse>(
      `/actions?limit=${limit}${runId ? `&run_id=${runId}` : ""}`,
    ),

  cash: () => request<Cash>("/cash/checking"),

  pay: (
    resolutionId: number,
    body: { amount: number; approved_by: string; memo: string },
  ) =>
    request<{ approved: boolean; balance_after: number }>(
      `/approvals/${resolutionId}/pay`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  reset: () => request<{ reset: boolean }>("/admin/reset", { method: "POST" }),
};

export const API_BASE = BASE;
