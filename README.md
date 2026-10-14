# Campus Customs — Multi-Agent Shop

A five-agent team that works the customer tickets of a Yale apparel shop, backed by one MCP server,
a FastAPI backend and a React dashboard.

**Boss · Inventory · Accounting · Facilities · Customer Service** — fully connected, all sharing one
MCP server over stdio, all running `gpt-5.6-luna` through Portkey.

The Boss decides. The specialists advise. Nothing in the agent layer can spend money or change what
the shop sells — that takes a named human and a separate route.

---

## What it does

The shop has three real unresolved customer requests sitting in its chat log:

| Ticket | Customer asked | Why it failed |
|---|---|---|
| **T1** gym shorts | "im looking for gym shorts" | **Assortment gap** — the shop carries only tops |
| **T2** Handsome Dan | "any item with handsome dan" | **Vocabulary gap** — the mascot is indexed as "bulldog" |
| **T3** emerald hoodie | "bright emerald green hoodie?" | **Colour gap** — `colors` is free text; no "emerald" |

The team diagnoses each, decides what to do, and records the decision. In the run of record it
declined to buy gym shorts (no unit cost, no sales history, one request), and resolved the other two
by correcting search — moving **$0.00**. See `output/desk_tickets.html` for expected-vs-actual on
each ticket and `output/resolved_board.html` for screenshots.

---

## Setup

```bash
git clone <this repo>
cd hw5
```

**1. Python environment**

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

The version floors in `requirements.txt` are deliberate. `pydantic-ai` 1.x and 2.x expose different
MCP APIs and this code uses the 2.x one, so an older install fails at import.

**2. API key**

```bash
cp .env.example .env
```

Put your Portkey key in `PORTKEY_API_KEY`. `.env` is gitignored and is read at runtime — it is never
hard-coded, logged, or written into the audit trail. The key may live in this folder or any parent;
the loader walks upward until it finds one.

**3. Frontend dependencies**

```bash
cd frontend && npm install && cd ..
```

---

## Making a clean working copy of the database

Two database files, and the distinction matters:

| File | Role |
|---|---|
| `data/campus_customs.db` | **Baseline.** Pristine, never written to by anything. |
| `data/campus_customs_new.db` | **Working copy.** Everything the agents and the API touch. |

A clean run means overwriting the working copy from the baseline:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

```powershell
Copy-Item data/campus_customs.db data/campus_customs_new.db -Force
```

That resets the catalogue, inventory, users and chat log, and discards every `ticket_resolutions`
and `cash_transactions` row written since the last reset. The operational tables — `cash_accounts`
seeded at **$25,000**, `cash_transactions`, `ticket_resolutions` — are recreated automatically the
next time the API starts, so you never need to build them by hand.

The tickets return to **Open** after a copy, because ticket status is derived from whether a
resolution row exists, not stored as a flag.

> Do this before any run you intend to present. The run of record in `output/` was produced from a
> freshly copied database, which is why its cash ledger starts clean.

---

## Running it

Three processes. The MCP server is usually started *for* you — see below.

### MCP server

```bash
python mcp_server/server.py          # stdio (default)
python mcp_server/server.py --http   # http://127.0.0.1:8002/mcp
```

**You normally do not run this yourself.** The agents launch it over stdio using `.mcp.json`, one
subprocess per run, and shut it down afterwards. Start it manually only to exercise the tools
directly or to attach an MCP client over HTTP.

To check all seven tools against the live database:

```bash
python mcp_server/smoke_test.py      # writes output/mcp_smoke.json
```

### FastAPI backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Interactive docs at <http://127.0.0.1:8000/docs>. On startup it creates the operational tables and
seeds checking if they are missing, so a freshly copied database is ready immediately.

### React dashboard

```bash
cd frontend
npm run dev
```

Opens on <http://localhost:5173>, which is already in the backend's CORS allow-list. Start the
backend first or the board will tell you it cannot reach `localhost:8000`.

### Running the team from the command line

```bash
python backend/run_team.py "Review every open ticket and decide what we do."
```

---

## Resetting the database

Two ways, same effect.

**From the dashboard** — the **↺ Reset** button in the top bar, with a confirmation.

**From the API:**

```bash
curl -X POST http://127.0.0.1:8000/admin/reset
```

Either one copies the baseline over the working copy, re-seeds checking at $25,000, and returns a
count of what it cleared.

**What reset does not touch:** `output/audit_trail.json`. The record of what the agents did survives
a data reset, deliberately. A reset that erased its own history would be a cover-up rather than a
rollback — so after resetting you will still find every run that produced the data you just deleted.

The baseline `data/campus_customs.db` is also never written to, by reset or by anything else.

---

## API routes

| Route | What it does |
|---|---|
| `GET /tickets` | The 3 tickets with Open/Resolved status |
| `GET /tickets/{id}` | One ticket by ref, e.g. `T1-gym-shorts` |
| `POST /tickets/{id}/run` | Runs the full agent team on that ticket |
| `GET /tickets/{id}/history` | Replays the last run for a ticket from the audit trail |
| `POST /tickets/{id}/resolve` | Marks it Resolved by recording a human decision |
| `GET /actions` | Recent agent actions: who acted, what they said, tools used |
| `POST /approvals/{id}/pay` | Debits checking — the only route that moves money |
| `GET /cash/checking` | Balance from `cash_accounts` plus recent movements |
| `POST /admin/reset` | Restores the working DB from the baseline |
| `GET /health` | Liveness, model, database, agent roster |

---

## The seven MCP tools

| # | Tool | Reads / writes |
|---|---|---|
| 1 | `search_products` | reads `catalogue` + `inventory` — expands customer wording into catalogue vocabulary |
| 2 | `check_stock` | reads `inventory` — returns `can_promise`, the only basis for telling a customer yes |
| 3 | `find_unmet_demand` | reads `chat_messages` + `users` — mines failed searches into classified tickets |
| 4 | `inventory_health` | reads `inventory` — stockout and reorder picture |
| 5 | `revenue_exposure` | reads `inventory` + `catalogue` — shelf value at retail, never revenue |
| 6 | `check_asset_integrity` | reads `catalogue` + filesystem — verifies the links SQLite does not enforce |
| 7 | `record_ticket_resolution` | **writes** `ticket_resolutions`, append-only |

Six are read-only, opened with `mode=ro` so a write is refused at the SQLite layer. Details in
[`mcp_server/README.md`](mcp_server/README.md).

---

## Safety

- **Agents cannot spend.** `POST /approvals/{id}/pay` is an operator route with no agent-facing tool
  behind it. It refuses a non-positive amount, a missing approver, an approver named after one of
  the five agents, a resolution not already on the record, and any overdraw.
- **No unverified promises.** `check_stock` gates every product named to a customer. About 24% of
  product-size rows are sold out at any time.
- **No invented economics.** There is no sales or order table, so Accounting is required to say that
  revenue and payback are not computable rather than estimate them.
- **Append-only audit.** Every loop step lands in `output/audit_trail.json`. A write that would
  shrink the record count raises instead of truncating; an unparseable trail is quarantined, never
  discarded. Credentials and password hashes are redacted at any nesting depth.

Full treatment, including the limits a real deployment would still have to close, is in
[`output/harness.md`](output/harness.md).

---

## Repository layout

```
hw5/
├── AI_prompts.md              every prompt used, with what each response missed
├── requirements.txt           pinned to verified versions
├── .env.example               template — real .env is gitignored
├── .mcp.json                  MCP server registration (portable paths)
├── data/
│   ├── campus_customs.db      baseline, never written
│   ├── campus_customs_new.db  working copy
│   └── products/              102 product images
├── mcp_server/
│   ├── server.py              FastMCP server, 7 tools
│   ├── smoke_test.py          drives every tool through a real MCP client
│   └── README.md
├── backend/
│   ├── main.py                FastAPI app
│   ├── models.py              typed agent hand-offs
│   ├── boss.py                orchestration and delegation
│   ├── specialists.py         the four advisors
│   ├── config.py              Portkey model + shared MCP toolset
│   ├── audit.py               append-only trail writer
│   ├── shop_data.py           operator-side DB access (money lives here)
│   ├── run_team.py            CLI entry point
│   └── prompts/               one .md per agent
├── frontend/                  React + Vite + TypeScript dashboard
└── output/
    ├── harness.md             tables, tools, agents, routes, dashboard, safety
    ├── desk_tickets.html      expected vs actual per ticket, cash, reflection
    ├── resolved_board.html    screenshots of the resolved board
    ├── resolved_tickets.json  machine-readable run of record
    ├── audit_trail.json       append-only agent audit log
    ├── mcp_smoke.json         tool test evidence
    ├── design.md              dashboard design rationale
    └── github_url.txt         link to this repo
```

---

Built for MGT 409 — AI Foundations for Managers, Yale SOM.
