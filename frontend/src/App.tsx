import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  AgentAction,
  Cash,
  RunResult,
  SpecialistReport,
  Ticket,
} from "./types";

const AGENTS = ["Boss", "Inventory", "Accounting", "Facilities", "CustomerService"] as const;

const FACE: Record<string, string> = {
  Boss: "🎩",
  Inventory: "📦",
  Accounting: "💰",
  Facilities: "🔧",
  CustomerService: "💬",
  orchestrator: "⚙️",
};

const LABEL: Record<string, string> = {
  Boss: "Boss",
  Inventory: "Inventory",
  Accounting: "Accounting",
  Facilities: "Facilities",
  CustomerService: "Cust. Service",
};

/** Shown while the team is thinking. A full loop takes tens of seconds, so
 *  the wait needs something better than a bare spinner. */
const WAITING = [
  "Boss is reading the tickets…",
  "Specialists are checking the shelf…",
  "Counting bulldogs in the catalogue…",
  "Nobody is promising anything unverified…",
  "Cross-checking every size before we answer…",
  "Accounting is refusing to forecast revenue…",
  "Still working — real model, real database…",
];

const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });

const clock = (iso: string) => {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
};

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [cash, setCash] = useState<Cash | null>(null);
  const [cashFlash, setCashFlash] = useState(false);

  const [running, setRunning] = useState(false);
  const [waitIdx, setWaitIdx] = useState(0);
  const [feed, setFeed] = useState<AgentAction[]>([]);
  const [result, setResult] = useState<RunResult | null>(null);
  const [historyRun, setHistoryRun] = useState<string | null>(null);

  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // easter egg state
  const [barks, setBarks] = useState(0);
  const [showBark, setShowBark] = useState(false);
  const [dan, setDan] = useState(false);
  const [boola, setBoola] = useState(false);

  const feedEnd = useRef<HTMLDivElement>(null);
  const baseline = useRef(0);

  const ticket = tickets.find((t) => t.ticket_id === selected) ?? null;

  const flash = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2600);
  };

  const loadTickets = useCallback(async () => {
    try {
      const d = await api.tickets();
      setTickets(d.tickets);
      setSelected((s) => s ?? d.tickets[0]?.ticket_id ?? null);
      setErr(null);
    } catch (e) {
      setErr(
        `Cannot reach the backend at localhost:8000 — ${(e as Error).message}. ` +
          `Start it with: uvicorn main:app --reload --port 8000`,
      );
    }
  }, []);

  const loadCash = useCallback(async () => {
    try {
      setCash(await api.cash());
    } catch {
      /* the ticket-load error already says the backend is down */
    }
  }, []);

  useEffect(() => {
    loadTickets();
    loadCash();
  }, [loadTickets, loadCash]);

  /* ── live feed: poll the audit trail while the team works ────────────── */
  useEffect(() => {
    if (!running) return;
    const tick = window.setInterval(async () => {
      try {
        const d = await api.actions(80);
        setFeed(d.actions.slice(baseline.current));
      } catch {
        /* transient; the run itself reports real failures */
      }
    }, 1500);
    const msg = window.setInterval(
      () => setWaitIdx((i) => (i + 1) % WAITING.length),
      3200,
    );
    return () => {
      window.clearInterval(tick);
      window.clearInterval(msg);
    };
  }, [running]);

  useEffect(() => {
    feedEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [feed.length]);

  /* ── load the last completed run for the selected ticket ─────────────── */
  useEffect(() => {
    if (!selected || running) return;
    let cancelled = false;
    (async () => {
      try {
        const h = await api.history(selected);
        if (cancelled) return;
        setFeed(h.actions);
        setHistoryRun(h.run_id);
      } catch {
        if (!cancelled) {
          setFeed([]);
          setHistoryRun(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, running]);

  /* ── easter eggs ─────────────────────────────────────────────────────── */
  useEffect(() => {
    const KONAMI = [
      "ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown",
      "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a",
    ];
    let seq: string[] = [];
    let typed = "";

    const onKey = (e: KeyboardEvent) => {
      seq = [...seq, e.key].slice(-KONAMI.length);
      if (seq.join() === KONAMI.join()) {
        setBoola((b) => !b);
        flash("🐶 Boola Boola mode toggled");
        seq = [];
      }
      if (e.key.length === 1) {
        typed = (typed + e.key.toLowerCase()).slice(-11);
        if (typed.includes("handsome")) {
          setDan(true);
          window.setTimeout(() => setDan(false), 5600);
          flash("🐶 Handsome Dan says hello");
          typed = "";
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    document.body.classList.toggle("boola", boola);
  }, [boola]);

  const pokeMark = () => {
    const n = barks + 1;
    setBarks(n);
    setShowBark(true);
    window.setTimeout(() => setShowBark(false), 1400);
    if (n === 5) {
      setDan(true);
      window.setTimeout(() => setDan(false), 5600);
      flash("🦴 You found the good boy");
      setBarks(0);
    }
  };

  /* ── actions ─────────────────────────────────────────────────────────── */
  const startRun = async () => {
    if (!ticket) return;
    setRunning(true);
    setResult(null);
    setFeed([]);
    setErr(null);
    setOk(null);
    try {
      const d = await api.actions(1);
      baseline.current = d.total_on_file;
    } catch {
      baseline.current = 0;
    }
    try {
      const r = await api.runTeam(ticket.ticket_id);
      setResult(r);
      if (r.error) setErr(r.error);
      else {
        setOk(`Run complete — ${r.summary}`);
        flash("✅ Team finished");
      }
      await Promise.all([loadTickets(), loadCash()]);
      try {
        const d = await api.actions(80, r.run_id);
        setFeed(d.actions);
      } catch { /* keep the polled feed */ }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const markResolved = async () => {
    if (!ticket) return;
    const decision = window.prompt(
      `Close ${ticket.ticket_id}. What was decided?`,
      result?.decisions[0]?.decision ?? "",
    );
    if (!decision) return;
    const rationale = window.prompt("Why? (a resolution with no reasoning is rejected)", "");
    if (!rationale) return;
    const who = window.prompt("Who is closing it?", "");
    if (!who) return;
    try {
      await api.resolve(ticket.ticket_id, {
        decision,
        rationale,
        resolved_by: who,
      });
      await loadTickets();
      setOk(`${ticket.ticket_id} marked Resolved.`);
      flash("🗂️ Ticket resolved");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const doReset = async () => {
    if (!window.confirm("Restore the working database from the baseline?\n\nThis clears resolutions and transactions. The audit trail is untouched.")) return;
    try {
      await api.reset();
      setResult(null);
      setFeed([]);
      await Promise.all([loadTickets(), loadCash()]);
      setOk("Database reset. Audit trail preserved.");
      flash("↺ Reset complete");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const onPaid = async () => {
    await loadCash();
    setCashFlash(true);
    window.setTimeout(() => setCashFlash(false), 950);
    flash("💸 Payment recorded");
  };

  /* ── derived: who is active right now ────────────────────────────────── */
  const lastActor = feed.length ? feed[feed.length - 1].actor : null;
  const seenActors = new Set(feed.map((f) => f.actor));

  const reports: SpecialistReport[] = result?.reports ?? [];
  const pendingApproval = (result?.decisions ?? []).filter((d) => d.needs_human_approval);

  return (
    <div className="shell">
      {/* ───────────── rail ───────────── */}
      <aside className="rail">
        <div className="brand" style={{ position: "relative" }}>
          <div
            className={`brand-mark${showBark ? " pop" : ""}`}
            onClick={pokeMark}
            title="Do not poke the bulldog"
          >
            🐶
          </div>
          {showBark && <div className="bark">Woof!</div>}
          <div>
            <h1>Campus Customs</h1>
            <p>Agent desk · 5 agents · 7 tools</p>
          </div>
        </div>

        <div className="rail-head">
          <span>Tickets</span>
          <span>
            {tickets.filter((t) => t.status === "Open").length} open
          </span>
        </div>

        <div className="tickets">
          {tickets.map((t) => (
            <button
              key={t.ticket_id}
              className={`tcard${t.ticket_id === selected ? " sel" : ""}`}
              onClick={() => {
                setSelected(t.ticket_id);
                setResult(null);
                setErr(null);
                setOk(null);
              }}
            >
              <div className="row">
                <span className="id">{t.ticket_id}</span>
                <span className={`dot ${t.status === "Open" ? "open" : "res"}`}>
                  {t.status}
                </span>
              </div>
              <p className="ask">“{t.customer_asked}”</p>
              <p className="who">
                {t.customer}
                {t.times_asked > 1 && ` · asked ${t.times_asked}×`}
              </p>
            </button>
          ))}
          {!tickets.length && (
            <p style={{ color: "#8d9bae", fontSize: 13, padding: "8px 3px" }}>
              No tickets loaded.
            </p>
          )}
        </div>

        <div className="cash">
          <div className="lbl">Checking</div>
          <div className={`amt${cashFlash ? " flash" : ""}`}>
            {cash?.balance != null ? money(cash.balance) : "—"}
          </div>
          <div className="sub">
            {cash?.balance != null
              ? `opened at ${money(cash.opening_balance)} · ${cash.recent_transactions.length} movement(s)`
              : "backend offline"}
          </div>
        </div>
      </aside>

      {/* ───────────── main ───────────── */}
      <main className="main">
        <div className="topbar">
          <div>
            <h2>{ticket ? ticket.ticket_id : "Campus Customs"}</h2>
            <p className="sub">
              {ticket
                ? `${ticket.customer} · ${ticket.classification.replace(/_/g, " ")}`
                : "Select a ticket to begin"}
            </p>
          </div>
          <div className="actions">
            <button className="btn primary" onClick={startRun} disabled={!ticket || running}>
              {running ? <><span className="spin" />Running…</> : "▶ Run agent team"}
            </button>
            <button
              className="btn"
              onClick={markResolved}
              disabled={!ticket || running || ticket.status === "Resolved"}
            >
              ✓ Mark resolved
            </button>
            <button className="btn ghost" onClick={() => { loadTickets(); loadCash(); }} disabled={running}>
              ↻ Refresh
            </button>
            <button className="btn ghost" onClick={doReset} disabled={running}>
              ↺ Reset
            </button>
          </div>
        </div>

        {err && <div className="alert err">{err}</div>}
        {ok && <div className="alert ok">{ok}</div>}

        {!ticket ? (
          <div className="empty">
            <div className="big">🧾</div>
            <p>Pick a ticket from the left to get started.</p>
          </div>
        ) : (
          <>
            {/* ticket */}
            <div className="card">
              <h3>The ask</h3>
              <div className="quote">“{ticket.customer_asked}”</div>
              <div className="chips">
                <span className="chip dark">{ticket.classification.replace(/_/g, " ")}</span>
                <span className="chip">{ticket.customer_email}</span>
                <span className={`chip ${ticket.status === "Open" ? "blue" : ""}`}>
                  {ticket.status}
                </span>
                {ticket.unmatched_terms.length > 0 && (
                  <span className="chip warn">
                    unmatched: {ticket.unmatched_terms.join(", ")}
                  </span>
                )}
              </div>
              {ticket.would_now_find.length > 0 && (
                <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 0, marginTop: 13 }}>
                  Search would now find:{" "}
                  {ticket.would_now_find.map((p) => `${p.name} ($${p.price})`).join(" · ")}
                </p>
              )}
            </div>

            {/* agent stage */}
            <div className="card">
              <h3>The team</h3>
              <div className="stage">
                {AGENTS.map((a) => {
                  const active = running && lastActor === a;
                  const done = !running && seenActors.has(a);
                  return (
                    <div key={a} className={`agent${active ? " active" : ""}${done ? " done" : ""}`}>
                      <span className="face">{FACE[a]}</span>
                      <div className="nm">{LABEL[a]}</div>
                      <div className="st">
                        {active ? "working…" : done ? "reported" : seenActors.size ? "not consulted" : "idle"}
                      </div>
                    </div>
                  );
                })}
              </div>
              {running && (
                <p style={{ textAlign: "center", color: "var(--muted)", fontSize: 13, margin: "15px 0 0" }}>
                  <span className="spin" />
                  {WAITING[waitIdx]}
                </p>
              )}
            </div>

            {/* live feed */}
            {feed.length > 0 && (
              <div className="card">
                <h3>
                  {running
                    ? "What the agents are doing"
                    : `What the agents did · ${historyRun ?? "this run"}`}
                </h3>
                <div className="feed">
                  {feed.map((a) => (
                    <div className="ev" key={`${a.run_id}-${a.seq}`}>
                      <div className="av">{FACE[a.actor] ?? "•"}</div>
                      <div className="bd">
                        <div className="hd">
                          <span className="who">{LABEL[a.actor] ?? a.actor}</span>
                          <span className="kind">{a.step_type}</span>
                          {a.tool_used && <span className="tool">{a.tool_used}()</span>}
                          <span style={{ fontSize: 10.5, color: "var(--muted)" }}>{clock(a.ts)}</span>
                        </div>
                        {a.said && <div className="txt">{a.said}</div>}
                      </div>
                    </div>
                  ))}
                  <div ref={feedEnd} />
                </div>
              </div>
            )}

            {/* summary of what each agent did */}
            {result && (
              <>
                <div className="card">
                  <h3>Run summary</h3>
                  <p style={{ marginTop: 0, fontSize: 14 }}>{result.summary}</p>
                  <div className="chips">
                    <span className="chip dark">{result.run_id}</span>
                    <span className="chip">{result.model}</span>
                    <span className="chip">{result.steps_logged} audit steps</span>
                    <span className="chip">{result.reports.length} report(s)</span>
                    {result.escalations.length > 0 && (
                      <span className="chip warn">{result.escalations.length} escalation(s)</span>
                    )}
                  </div>
                </div>

                {result.decisions.length > 0 && (
                  <div className="card">
                    <h3>Decisions</h3>
                    {result.decisions.map((d, i) => (
                      <div className="rep" key={i}>
                        <div className="hd">
                          <div className="nm">🎩 {d.ticket_ref}</div>
                          <div style={{ display: "flex", gap: 6 }}>
                            <span className="chip">owner: {LABEL[d.owner] ?? d.owner}</span>
                            {d.needs_human_approval && <span className="chip warn">needs approval</span>}
                          </div>
                        </div>
                        <p><b>{d.decision}</b></p>
                        <div className="rec">{d.rationale}</div>
                      </div>
                    ))}
                  </div>
                )}

                {reports.length > 0 && (
                  <div className="card">
                    <h3>What each agent said</h3>
                    {reports.map((r, i) => (
                      <div className="rep" key={i}>
                        <div className="hd">
                          <div className="nm">
                            <span>{FACE[r.agent] ?? "•"}</span>
                            {LABEL[r.agent] ?? r.agent}
                          </div>
                          <div style={{ display: "flex", gap: 6 }}>
                            <span className={`chip ${r.confidence === "high" ? "blue" : ""}`}>
                              {r.confidence} confidence
                            </span>
                            {r.needs_human && <span className="chip warn">escalated</span>}
                          </div>
                        </div>
                        <p>{r.summary}</p>
                        <div className="rec">
                          <b>Recommends:</b> {r.recommendation}
                        </div>
                        {r.findings.map((f, j) => (
                          <div className="find" key={j}>
                            <div>• {f.statement}</div>
                            <div className="evi">{f.evidence}</div>
                          </div>
                        ))}
                        {r.escalation_reason && (
                          <div className="find" style={{ color: "#8a5a00" }}>
                            ⚠ {r.escalation_reason}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {/* approvals */}
            <ApprovalCard
              pending={pendingApproval.length}
              resolutions={ticket.resolutions}
              onPaid={onPaid}
            />

            {/* money movements */}
            {cash && cash.recent_transactions.length > 0 && (
              <div className="card">
                <h3>Recent movements</h3>
                {cash.recent_transactions.map((t) => (
                  <div className="txn" key={t.txn_id}>
                    <div>
                      <div style={{ fontWeight: 600 }}>{t.memo}</div>
                      <div style={{ color: "var(--muted)", fontSize: 12 }}>
                        approved by {t.approved_by} · resolution #{t.resolution_id} · {t.created_at}
                      </div>
                    </div>
                    <div className="amt">−{money(t.amount)}</div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </main>

      {dan && <div className="dan">🐕</div>}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

/* ───────────────────────── approval form ───────────────────────── */
function ApprovalCard({
  pending,
  resolutions,
  onPaid,
}: {
  pending: number;
  resolutions: Ticket["resolutions"];
  onPaid: () => void;
}) {
  const [resId, setResId] = useState("");
  const [amount, setAmount] = useState("");
  const [who, setWho] = useState("");
  const [memo, setMemo] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (!resId && resolutions.length) setResId(String(resolutions[resolutions.length - 1].resolution_id));
  }, [resolutions, resId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.pay(Number(resId), {
        amount: Number(amount),
        approved_by: who,
        memo,
      });
      setMsg({ kind: "ok", text: `Approved. New balance ${money(r.balance_after)}.` });
      setAmount("");
      setMemo("");
      onPaid();
    } catch (e) {
      setMsg({ kind: "err", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h3>Human approval {pending > 0 && `· ${pending} awaiting`}</h3>
      <p style={{ marginTop: 0, fontSize: 13, color: "var(--muted)" }}>
        Agents can recommend spend. Only a named human can release it, and only against a
        resolution already on the record.
      </p>

      {msg && <div className={`alert ${msg.kind === "ok" ? "ok" : "err"}`}>{msg.text}</div>}

      {resolutions.length === 0 ? (
        <p style={{ fontSize: 13, color: "var(--muted)", margin: 0 }}>
          No recorded resolution for this ticket yet — run the team or mark it resolved first.
        </p>
      ) : (
        <form onSubmit={submit}>
          <div className="grid2">
            <div className="field">
              <label>Resolution</label>
              <select
                value={resId}
                onChange={(e) => setResId(e.target.value)}
                style={{
                  width: "100%", padding: "9px 12px", border: "1px solid var(--line)",
                  borderRadius: 8, background: "#fff",
                }}
              >
                {resolutions.map((r) => (
                  <option key={r.resolution_id} value={r.resolution_id}>
                    #{r.resolution_id} — {r.decision.slice(0, 44)}…
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Amount (USD)</label>
              <input
                type="number" min="0.01" step="0.01" required
                value={amount} onChange={(e) => setAmount(e.target.value)}
                placeholder="1800.00"
              />
            </div>
          </div>
          <div className="field">
            <label>Approved by (a human — agent names are rejected)</label>
            <input
              required value={who} onChange={(e) => setWho(e.target.value)}
              placeholder="Your name"
            />
          </div>
          <div className="field">
            <label>Memo</label>
            <input
              required value={memo} onChange={(e) => setMemo(e.target.value)}
              placeholder="Gym shorts pilot order, 60 units"
            />
          </div>
          <button className="btn primary" disabled={busy}>
            {busy ? <><span className="spin" />Approving…</> : "💸 Approve payment"}
          </button>
        </form>
      )}
    </div>
  );
}
