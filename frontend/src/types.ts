export type TicketStatus = "Open" | "Resolved";

export interface Resolution {
  resolution_id: number;
  ticket_ref: string;
  decision: string;
  rationale: string;
  decided_by: string;
  owner: string;
  product_ids: string;
  recorded_at: string;
}

export interface Ticket {
  ticket_id: string;
  status: TicketStatus;
  customer: string;
  customer_email: string;
  customer_asked: string;
  asked_at: string;
  times_asked: number;
  classification: "true_assortment_gap" | "fixable_by_search" | string;
  suggested_owner: string;
  unmatched_terms: string[];
  would_now_find: { product_id: string; name: string; price: number }[];
  resolutions: Resolution[];
}

export interface TicketsResponse {
  count: number;
  open: number;
  resolved: number;
  tickets: Ticket[];
}

export interface Finding {
  statement: string;
  evidence: string;
  severity: "info" | "warning" | "blocker";
  tools_used: string[];
}

export interface SpecialistReport {
  agent: string;
  summary: string;
  findings: Finding[];
  recommendation: string;
  confidence: "high" | "medium" | "low";
  needs_human: boolean;
  escalation_reason: string | null;
}

export interface Decision {
  ticket_ref: string;
  customer_ask: string;
  classification: string;
  decision: string;
  rationale: string;
  owner: string;
  product_ids: string[];
  consulted: string[];
  needs_human_approval: boolean;
  recorded_resolution_id: number | null;
}

export interface RunResult {
  ticket_id: string;
  model: string;
  run_id: string;
  summary: string;
  decisions: Decision[];
  reports: SpecialistReport[];
  escalations: string[];
  steps_logged: number;
  error: string | null;
}

export interface AgentAction {
  run_id: string;
  seq: number;
  ts: string;
  actor: string;
  step_type: string;
  said: string;
  tool_used: string | null;
  tools_in_report: string[] | null;
  model: string | null;
  duration_ms: number | null;
  tokens: { input: number; output: number } | null;
}

export interface ActionsResponse {
  count: number;
  total_on_file: number;
  runs: string[];
  tool_call_counts: Record<string, number>;
  actions: AgentAction[];
  note?: string;
}

export interface CashTxn {
  txn_id: number;
  account_name: string;
  amount: number;
  direction: "debit" | "credit";
  memo: string;
  resolution_id: number | null;
  approved_by: string;
  balance_after: number;
  created_at: string;
}

export interface Cash {
  account_name: string;
  balance: number | null;
  currency: string;
  updated_at: string;
  opening_balance: number;
  recent_transactions: CashTxn[];
  error?: string;
}
