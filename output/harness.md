# Data Harness — `data/campus_customs.db`

Reference for the multi-agent shop system (Boss, Inventory, Accounting, Facilities, Customer Service).
Working copy for agent writes: `data/campus_customs_new.db`. The original `campus_customs.db` stays read-only as a rollback baseline.

SQLite, 4 application tables (+ `sqlite_sequence`, an SQLite-internal AUTOINCREMENT counter — ignore it).

| Table | Rows | Role |
|---|---|---|
| `catalogue` | 102 | What the shop sells |
| `inventory` | 612 | How much of it is on the shelf, by size |
| `users` | 4 | Who the customers are |
| `chat_messages` | 18 | What customers asked and what the shop answered |

---

## 1. `catalogue` — product master (102 rows)

| Field | Type | Meaning | Why it's useful |
|---|---|---|---|
| `product_id` | TEXT **PK** | Slug ID, e.g. `2025-yale-vs-harvard-t-shirt` | The join key for the whole DB. Also matches the image filename stem, so ID → picture needs no lookup. |
| `name` | TEXT | Display name, e.g. `2025 Yale Vs Harvard T Shirt` | What Customer Service and the dashboard show a human. Never use it as a key — it isn't unique-constrained. |
| `garment_type` | TEXT | Category, e.g. `pullover hoodie` | Rollups and filtering ("show me hoodies"). **Dirty: 22 distinct values with overlaps** (`t-shirt` vs `short-sleeve T-shirt` vs `short-sleeve t-shirt`; `hoodie` vs `pullover hoodie`). Normalize before any category report, or counts will be wrong. |
| `description` | TEXT | Full prose description of the garment and graphic | Primary text for semantic/keyword search. This is where "Handsome Dan", "bulldog", "The Game" actually live. |
| `colors` | TEXT (JSON array) | e.g. `["heather gray","white","red","navy blue"]` | Color filtering. Stored as a JSON string, not a relation — must be parsed or matched with `LIKE`. Vocabulary is free-text, so "emerald green" won't match "green". |
| `search_tags` | TEXT (JSON array) | Curated keywords, e.g. `["Yale","Harvard","The Game","college rivalry"]` | Hand-tuned retrieval boost. Cheaper and more precise than scanning `description` for common queries. |
| `image_file_path` | TEXT | Relative path, e.g. `products/2025-yale-vs-harvard-t-shirt.jpg` | Feeds the React dashboard and any vision call. Relative to `data/`, so it survives moving the project. |
| `price` | REAL | USD unit price, e.g. `32.0` | Accounting's input for revenue, margin, and inventory valuation; Customer Service's input for "what's your cheapest fleece?". |

## 2. `inventory` — stock on hand (612 rows)

| Field | Type | Meaning | Why it's useful |
|---|---|---|---|
| `id` | INTEGER **PK** AUTOINCREMENT | Surrogate row ID | Stable handle for a single update; carries no business meaning. |
| `product_id` | TEXT **FK → catalogue** | Which product | The join back to price, name, and image. All 612 rows resolve — **zero orphans**. |
| `size` | TEXT | One of `XS, S, M, L, XL, XXL` | Stock is only meaningful per size. "In stock" without a size is a half-answer that causes bad promises to customers. |
| `quantity` | INTEGER | Units on hand | Inventory's core signal — reorder points, stockouts, and the gate on whether Customer Service may promise an item. **145 of 612 rows (24%) sit at 0**, so stockouts are the normal case, not the exception. |
| — | UNIQUE(`product_id`,`size`) | One row per product-size | Guarantees no double-counting; also makes `UPSERT` safe for stock adjustments. |

The grain is exactly complete: 612 = 102 × 6, so **every product currently carries all six sizes**, and unavailability today always means `quantity = 0` ("carried but sold out"), never a missing row ("size not carried"). The two are still different claims, and the schema permits a missing row, so `check_stock` reports them separately as `sold_out` vs `not_carried` — defensive against a future product that skips a size, but `not_carried` does not fire on today's data.

## 3. `users` — customer accounts (4 rows)

| Field | Type | Meaning | Why it's useful |
|---|---|---|---|
| `id` | INTEGER **PK** | Account ID | Join key into `chat_messages`. |
| `name` | TEXT | Full name | Display. |
| `email` | TEXT **UNIQUE** | Login identity | The real identity constraint; dedupe and contact key for Customer Service follow-up. |
| `password_hash` | TEXT | Hashed credential | Auth only. **Never expose to an agent, a log, or the dashboard.** |
| `created_at` | TEXT | ISO timestamp | Cohort/tenure analysis; separates test accounts from real ones. |
| `first_name`, `last_name` | TEXT | Split name (added later via `ALTER TABLE`, hence nullable) | Lets agents greet by first name ("Hey Tauhid!"), which the chat log shows is the house style. |

## 4. `chat_messages` — conversation log (18 rows)

| Field | Type | Meaning | Why it's useful |
|---|---|---|---|
| `id` | INTEGER **PK** AUTOINCREMENT | Message ID, ascending = chronological | Orders a thread. **Has gaps** (…22, then 51) — rows were deleted, so never assume `id` is contiguous. |
| `user_id` | INTEGER **FK → users** | Whose conversation | Groups messages into per-customer threads and attaches a name/email for follow-up. |
| `role` | TEXT | `user` or `assistant` | Separates demand signal (what customers asked for) from shop response. Only `user` rows are evidence of unmet demand. |
| `content` | TEXT | Message body (Markdown in assistant replies) | The actual request/answer. Mining `user` rows yields the demand gaps Inventory should act on. |
| `products_json` | TEXT (JSON array, nullable) | Products the assistant surfaced, each with `product_id` + `name` | **The implicit link to `catalogue`.** An empty `[]` on an assistant reply = a failed search, i.e. a lost sale. The single most useful field for measuring shop performance. |
| `created_at` | TEXT | ISO timestamp | Session reconstruction and response latency. |

---

## The 3 open tickets, and how they link

> **Assumption, flagged:** this database has **no `tickets` table** — none exists in `campus_customs.db`, and nothing in the HW4 codebase defines one. The only thing matching "3 open tickets" is the **3 unresolved customer requests** in `chat_messages`: assistant replies returning `products_json = []` plus an explicit "I couldn't find…". Those are documented below. If "tickets" means a table that still needs to be created, say so and I'll build it.

| # | User | Request | Assistant outcome | Status |
|---|---|---|---|---|
| 1 | Tauhid Zaman (`users.id=3`) | "im looking for gym shorts" (msg 9) | "couldn't find any products matching 'gym shorts'" (msg 10) | **Open — assortment gap.** `catalogue.garment_type` has 22 values and **none are shorts**: the shop sells tops only. A real buying gap, not a search bug. |
| 2 | Tauhid Zaman (`users.id=3`) | "any item with handsome dan" (msgs 11, 13) | "couldn't find any items featuring Handsome Dan" (msgs 12, 14) | **Open — vocabulary gap.** The mascot *is* in the catalogue, indexed as "bulldog" in `description`/`search_tags`, never as "Handsome Dan". Proof: the very next turn, "bulldog" returned hits. Fix is a `search_tags` synonym, not new stock. |
| 3 | Test User (`users.id=1`) | "Do you have a bright emerald green hoodie?" (msg 51) | "couldn't pull up hoodie matches for bright emerald green" (msg 52) | **Open — color-matching gap.** `catalogue.colors` is a free-text JSON array; "emerald green" matches nothing literally. Hoodies are in stock; only the color vocabulary failed. |

### Link path

```
users.id                      ──<  chat_messages.user_id       (who opened it;        FK, enforced)
chat_messages.products_json   ──>  catalogue.product_id        (what was offered;     JSON, NOT enforced)
catalogue.product_id          ──<  inventory.product_id        (can we fulfill it;    FK, enforced)
catalogue.image_file_path     ──>  data/products/*.jpg         (what they see;        path, NOT enforced)
```

Reading a ticket end to end: `chat_messages` gives the ask and the identity → `users` gives the name and email to reply to → `products_json` (or a fresh search over `description` / `search_tags` / `colors`) gives candidate `product_id`s → `inventory` confirms a size is actually in stock before anything is promised → `catalogue.price` and `image_file_path` fill in the quote and the picture.

Two of those edges are **unenforced** — `products_json` and `image_file_path` are plain strings, not foreign keys. Agents must validate both rather than trust them.

### Agent ownership

- **Customer Service** — owns all 3 tickets; reads `chat_messages` + `users`, must check `inventory.quantity > 0` before promising anything.
- **Inventory** — owns #1 (stock a shorts line) and the stock side of #3; also owns the 145 zero-quantity rows.
- **Boss** — arbitrates #1: adding shorts is a buying decision, not a search fix.
- **Accounting** — prices any new SKU against the existing `price` distribution; quantifies the lost sales these 3 tickets represent.
- **Facilities** — no direct ticket stake; owns the DB file, backups, and the `data/products/` image assets the dashboard serves.

---

# MCP Tools — `mcp_server/`

One FastMCP server (`mcp_server/server.py`, server name `campus-customs-shop`) shared by all five
agents, reading **`data/campus_customs_new.db`** read-only. Agents hold the judgment; the server holds
the facts, so Boss, Inventory, Accounting, Facilities and Customer Service cannot contradict each other
about price or stock.

| Tool | Reads | Unlocks | Why it is right for that ticket |
|---|---|---|---|
| **`search_products(query, in_stock_only, limit)`** | `catalogue` (name, description, `search_tags`, `colors`, `garment_type`, `price`, `image_file_path`) joined to `inventory` for live per-size stock | **Ticket #2 — Handsome Dan** and **Ticket #3 — emerald green hoodie** | Both tickets failed for the same reason: the customer's words are not the catalogue's words. The mascot is indexed as "bulldog" and never as "Handsome Dan"; `colors` is free-text JSON where "emerald" matches nothing. This tool expands the query into catalogue vocabulary *before* matching, scores across five weighted fields, and matches on whole words so `"im"` no longer hits `"trim"`. It also returns `unmatched_terms`, which is what separates a search defect from a real buying gap — the exact distinction these two tickets turn on. |
| **`check_stock(product_id, size)`** | `inventory` (`size`, `quantity`, the UNIQUE product–size grain) joined to `catalogue` for name, price, colors and image | **The promise gate on all three tickets** — decisive for **#3**, where hoodies exist but the customer must be told which sizes are actually shippable | Finding a product is not the same as being able to sell it: 145 of 612 inventory rows (24%) are at quantity 0. This tool collapses that into one boolean, `can_promise`, and is the only sanctioned way to answer "do you have it". It is also the one tool that honours the missing-row-vs-zero-row distinction — `not_carried` ("we never stocked that size") versus `sold_out` ("carried, none left") — which a naive `quantity > 0` query silently conflates into a wrong promise. `low_stock` at ≤5 units gives Inventory a reorder signal before the next stockout. |
| **`find_unmet_demand(limit)`** | `chat_messages` (`role`, `content`, `products_json`, `created_at`) joined to `users` for name and email, then re-queried against `catalogue` | **Ticket #1 — gym shorts**, and it is what *generates* the ticket list in the first place | Ticket #1 is invisible from the product tables: you cannot see an absent category by reading the catalogue. The only evidence lives in the chat log, as a customer ask that returned nothing. This tool reconstructs each failed ask, re-runs it through today's search, and classifies the result — `true_assortment_gap` (nothing matches even after synonym expansion → **Inventory**, a purchasing decision) versus `fixable_by_search` (stock exists, the search was at fault → **Customer Service**). That classification is precisely the judgment the Boss needs for #1: buy shorts, rather than fix the search. |

### Why these three and not others

The three tickets fail at three different layers, so each tool closes a different one:

- **#2 and #3 fail at retrieval** — the goods exist, the words missed → `search_products`.
- **Any ticket can fail at fulfilment** — the words hit, the shelf is empty → `check_stock`.
- **#1 fails at assortment** — nothing exists to retrieve → `find_unmet_demand`.

### How the tools chain

```
find_unmet_demand()        -> which tickets are open, and whose problem each one is
   |                          (reads chat_messages + users)
   v
search_products(ask)       -> candidate product_ids, with synonyms expanded
   |                          (reads catalogue, previews inventory)
   v
check_stock(id, size)      -> can_promise: the only claim safe to make to a customer
                              (reads inventory, authoritative)
```

### Verified against the live database

- `search_products("any item with handsome dan")` → **3 matches**, including both *District Vit Crewneck Vintage Bulldog* items. Ticket #2 resolves without buying anything.
- `search_products("bright emerald green hoodie", in_stock_only=True)` → **3 in-stock hoodies** with sizes XS–XXL. Ticket #3 resolves as a color-vocabulary fix.
- `search_products("im looking for gym shorts")` → **0 matches**, `unmatched_terms = ["gym", "shorts"]`. Confirms ticket #1 is a true assortment gap.
- `find_unmet_demand()` → **exactly 3 open tickets**: 1 `true_assortment_gap`, 2 `fixable_by_search`, with the two Handsome Dan rephrasings collapsed into one ticket carrying `times_asked = 2`.

---

# The Agent Team

Five PydanticAI agents, all on `gpt-5.6-luna` through Portkey, all sharing the one MCP server defined
in `.mcp.json`. The Boss decides; the four specialists advise. Prompts live in `backend/prompts/`,
one `.md` per agent.

| Agent | Prompt | Owns | Primary tools | Authority |
|---|---|---|---|---|
| **Boss** | `boss.md` | The decision. Delegation, arbitration, recording resolutions. | `find_unmet_demand`, `record_ticket_resolution`, `ask_specialist` | Decides and records. Must flag spend, new SKUs and price changes for human approval. |
| **Inventory** | `inventory.md` | What is on the shelf, what is running out, what is not carried. | `inventory_health`, `check_stock`, `search_products` | Advises. May recommend a reorder; may never commit spend. |
| **Accounting** | `accounting.md` | Shelf value, sold-out exposure, whether a proposal is sized sensibly. | `revenue_exposure`, `inventory_health`, `search_products` | Advises. May not authorise spend or produce a revenue forecast. |
| **Facilities** | `facilities.md` | The DB file, image assets, and the links SQLite does not enforce. | `check_asset_integrity`, `inventory_health`, `search_products` | Advises. Has no write tool at all, by design. |
| **Customer Service** | `customer_service.md` | What the shop says to customers. | `search_products`, `check_stock`, `find_unmet_demand` | Drafts replies. A human sends them. |

All agents are given the full toolset and told in their own prompt which tools are theirs. That is
deliberate: full connectivity lets a specialist verify a neighbour's claim instead of taking it on trust.

## The seven MCP tools

| # | Tool | Reads / writes | Used by |
|---|---|---|---|
| 1 | `search_products` | reads `catalogue` + `inventory` | Customer Service, Inventory, Accounting, Facilities |
| 2 | `check_stock` | reads `inventory` + `catalogue` | Customer Service, Inventory |
| 3 | `find_unmet_demand` | reads `chat_messages` + `users` + `catalogue` | Boss, Customer Service |
| 4 | `inventory_health` | reads `inventory` + `catalogue` | Inventory, Accounting, Facilities |
| 5 | `revenue_exposure` | reads `inventory` + `catalogue` | Accounting |
| 6 | `check_asset_integrity` | reads `catalogue` + `chat_messages` + the `data/products/` filesystem | Facilities |
| 7 | `record_ticket_resolution` | **writes** `ticket_resolutions` (append-only) | Boss |

Tool 7 is the only write in the system. It inserts and never updates or deletes, so a wrong decision
is corrected by recording a new one rather than erasing the old.

## Audit trail

Every loop step appends one record to `output/audit_trail.json`: `run_started`, `delegation`,
`tool_call`, `specialist_report`, `escalation`, `decision`, `run_finished`, `error`. Each record
carries `run_id`, a monotonic `seq`, UTC `ts`, `actor`, `model`, a human-readable `summary`, the full
`payload`, and token counts where available.

The file is append-only and enforced as such in `backend/audit.py`: every write re-reads the file and
appends, a write that would shrink the record count raises instead of truncating, and an unparseable
trail is renamed to `audit_trail.corrupt-<timestamp>.json` rather than discarded.

---

# Safety

This section assumes the system is running a real business with real customers and real money.

## 1. The agents cannot spend money or change what is for sale

No tool in this server places an order, changes a price, adjusts stock, or creates a product. Six of
the seven tools are read-only against the database, opened with `mode=ro` so a write is refused at the
SQLite layer rather than merely avoided by convention. The seventh writes decisions to its own table
and touches nothing else.

The consequence: the worst outcome of a confused agent is a **wrong recommendation**, never a wrong
purchase order. Every prompt reinforces this - Inventory may recommend a reorder, Accounting may size
it, the Boss may decide it, but the spend itself requires a human.

## 2. Human approval is required where it matters

Agents set `needs_human: true` and the Boss sets `needs_human_approval: true` for anything that
commits the business: adding a product line, placing a reorder, changing a price, promising a restock
date, issuing a refund or discount, or sending a customer-facing message. Customer Service drafts;
a human sends. `escalation_reason` is required whenever `needs_human` is set - the model validator
rejects an escalation with no stated reason, so the reason cannot be silently dropped.

## 3. No invented facts

Every prompt forbids stating a product, price, size, or quantity that did not come from a tool call in
that run. Each `Finding` requires an `evidence` field citing the tool output behind it, and the Boss is
instructed to discount findings whose evidence is weak or whose `confidence` is `low`, and to say in
the rationale that it did so.

The sharpest instance is Accounting: this database has **no sales or order table**, so revenue, margin
and payback are not computable. The prompt requires Accounting to say that plainly rather than produce
a plausible number. A confident figure built on absent data is the most dangerous output this system
could generate, because it looks exactly like a real one.

## 4. The stock gate

About 24% of product-size rows are sold out at any moment, so "it is in the catalogue" and "we can
ship it" are different claims. `check_stock` returns a single `can_promise` boolean, and both the
Customer Service and Boss prompts make it the only acceptable basis for telling a customer yes. This
is the control that stops the shop promising goods it does not have.

## 5. Spend and blast-radius limits

`MAX_DELEGATIONS_PER_RUN = 12` caps specialist calls per question; the Boss's delegation tool refuses
beyond it and tells the Boss to decide with what it has or escalate. Without that cap a confused Boss
can loop specialists indefinitely against a paid API. Each agent also has `retries=2` rather than
unbounded retry.

## 6. Failure is visible, not silent

A specialist that crashes does not take down the run. The orchestrator catches it, writes an `error`
record to the audit trail, and returns a `confidence: low`, `needs_human: true` report so the Boss
sees that the agent was unavailable and decides without it. A missing opinion is never mistaken for
agreement.

## 7. Credentials and customer data

`PORTKEY_API_KEY` is read from the root `.env` at runtime and never hard-coded, logged, or placed in a
payload. The audit writer additionally redacts any key named like a credential - `api_key`,
`authorization`, `token`, `secret`, `password`, `password_hash` - at any nesting depth, because the
audit trail is the file most likely to be shared with an auditor or committed to a repository. No tool
returns `users.password_hash`.

## 8. The data itself is protected

Agents read `data/campus_customs_new.db`. The pristine `data/campus_customs.db` is never opened by the
server at all, so a rollback baseline always exists. The audit trail is append-only and atomically
written, falling back to a direct write only when a filesystem lock makes atomic replacement
impossible - losing a record is worse than a non-atomic write.

## 9. Known limits a real deployment must close

Stated plainly, because an unlisted limitation is the one that causes the incident:

- **No authentication or rate limiting** on the MCP server. It trusts any local caller.
- **No per-run cost ceiling in dollars** - the delegation cap bounds calls, not spend.
- **No PII minimisation.** `find_unmet_demand` returns customer names and email addresses into the
  audit trail by design, so the trail inherits personal data and must be access-controlled and
  retention-limited accordingly.
- **No human-in-the-loop enforcement in code.** `needs_human_approval` is a flag the agents set and a
  downstream system must honour; nothing yet blocks on it.
- **Prompt injection is not defended.** `chat_messages.content` is customer-supplied text that flows
  into agent context via `find_unmet_demand`. A hostile customer message is an untrusted input and
  should be treated as data, not instructions, before this is exposed to real traffic.

---

# API Routes — `backend/main.py`

Start from `backend/`:

```
uvicorn main:app --reload --port 8000
```

Interactive docs at `http://127.0.0.1:8000/docs`.

| Route | What it does |
|---|---|
| `GET /tickets` | The 3 tickets with Open/Resolved status, customer, classification and any recorded resolutions. |
| `GET /tickets/{ticket_id}` | One ticket by ref, e.g. `T1-gym-shorts`. 404s with the list of known ids. |
| `POST /tickets/{ticket_id}/run` | Runs the full agent team on that ticket; returns decisions, specialist reports and escalations. |
| `GET /actions?limit=&run_id=` | Recent agent actions from the audit trail: who acted, what they said, which tools they used. |
| `POST /approvals/{resolution_id}/pay` | Debits checking against a recorded decision, after a named human approves. The only route that moves money. |
| `GET /cash/checking` | Current checking balance from `cash_accounts`, plus the last 10 transactions. |
| `POST /admin/reset` | Restores the working DB from the untouched baseline and re-seeds cash. Does not touch the audit trail. |
| `POST /tickets/{ticket_id}/resolve` | Marks a ticket Resolved by recording a human decision (decision, rationale, who closed it) against it. |
| `GET /tickets/{ticket_id}/history` | The most recent completed run for a ticket, replayed from the audit trail so a page reload does not lose who worked it. |
| `GET /health` | Liveness, active model, database file, agent roster. |

## Two layers of authority

The API deliberately does **not** expose money movement to the agents. Agents reach the shop only
through the MCP server, which is read-only apart from recording decisions. `POST /approvals/{id}/pay`
is an operator route with no agent-facing tool behind it, and it refuses four distinct cases:

- a non-positive amount;
- a missing approver, **or an approver named after one of the five agents** — an agent cannot approve
  its own spend;
- a `resolution_id` that is not already on the record, so money only ever moves against a decision
  the Boss wrote down;
- any amount that would overdraw the account.

`cash_accounts` holds the balance and `cash_transactions` is an append-only log with `balance_after`
stamped on every row, so the balance can always be re-derived from the movements rather than trusted
on its own.

## What reset does and does not touch

`POST /admin/reset` copies `data/campus_customs.db` over `data/campus_customs_new.db`, which clears
`ticket_resolutions` and `cash_transactions` and returns checking to its $25,000 opening balance. It
never writes to the baseline, and it never touches `output/audit_trail.json`.

That last point is the important one: the record of what the agents did survives a data reset. A
reset that erased its own history would be a cover-up rather than a rollback.

---

# Frontend — `frontend/`

React + Vite + TypeScript. Start with:

```
cd frontend && npm run dev
```

Serves on `http://localhost:5173`, which is already in the backend's CORS allow-list. The API base is
`http://localhost:8000`, overridable with `VITE_API_BASE`.

| Requirement | Where it lives |
|---|---|
| List all tickets | Dark rail, always visible, with live open/resolved counts |
| Pick a ticket and start the team | Ticket cards in the rail; **Run agent team** in the top bar |
| Show what each agent is saying/doing | Agent stage (5 cards, active one animates) + live feed polling `/actions` |
| Mark a ticket resolved | **Mark resolved** — prompts for decision, rationale and who closed it |
| Summary of what each agent did | Run summary, Decisions, and "What each agent said" with findings and evidence |
| Human approval of a transaction | Approval card: resolution, amount, named human, memo |
| Checking balance | Pinned in the rail; flashes when it changes |

Design rationale is in `output/design.md`.

---

# Run of record — all three tickets

Database reset to the `campus_customs.db` baseline, then all three tickets run to resolution on
`gpt-5.6-luna`. Full detail in `output/resolved_tickets.json`; screenshots in
`output/resolved_board.html`; expected-vs-actual in `output/desk_tickets.html`.

| Ticket | Run | Delegations | Tools called | Outcome | Cash |
|---|---|---|---|---|---|
| T1 gym shorts | `…195012Z-c02be0` | Inventory → Accounting | `find_unmet_demand`, `search_products` ×2, `revenue_exposure`, `inventory_health` | Declined to buy; escalated for human approval | $0.00 |
| T2 Handsome Dan | `…195051Z-ebc4b9` | Customer Service | `find_unmet_demand`, `search_products`, `check_stock` ×5 | Corrected reply, five verified products | $0.00 |
| T3 emerald hoodie | `…195059Z-aaf53f` | Customer Service | `find_unmet_demand`, `search_products`, `check_stock` ×3 | Stated the colour gap, offered 3 verified hoodies | $0.00 |

36 audit steps, 17 MCP tool calls, 3 of 3 resolved.

**Cash reconciliation.** Opening $25,000.00 − $0.00 debits = **$25,000.00**, matching
`cash_accounts.balance` exactly, with zero rows in `cash_transactions`. Nothing moved because the
only ticket that could have cost money was one the team recommended against buying.

**Behaviours that held under a real run:**

- The stock gate: eight `check_stock` calls, one per product, before any product was named.
- Accounting refused to produce a payback figure rather than inventing one.
- Routing was correct on all three: two specialists for the buying question, one for each search defect.
- None of the three predicted failure modes occurred — no invented near-match for shorts, no
  unverified product named, no silently-dropped colour.

**Still outstanding after the run:** T3's colour-vocabulary gap was never fixed, so the next customer
asking for "emerald" fails identically. The Boss resolved the conversation, not the cause.

---

# Harness summary

Everything in the system, in one place.

## Database — `data/campus_customs_new.db`

Working copy; `data/campus_customs.db` is the untouched rollback baseline.

| Table | Rows | Role |
|---|---|---|
| `catalogue` | 102 | Product master: id, name, type, description, colors, tags, image path, price |
| `inventory` | 612 | Stock by product-size (102 × 6, complete grain). 145 rows at zero |
| `users` | 4 | Customer accounts |
| `chat_messages` | 18 | Conversation log; `products_json` is the implicit link to `catalogue` |
| `ticket_resolutions` | created on use | Append-only decision record |
| `cash_accounts` | 1 | Checking balance |
| `cash_transactions` | append-only | Money movements with `balance_after` stamped per row |

## MCP tools — `mcp_server/server.py`

| # | Tool | Reads / writes | Owner |
|---|---|---|---|
| 1 | `search_products` | reads `catalogue` + `inventory` | Customer Service |
| 2 | `check_stock` | reads `inventory` + `catalogue` | Customer Service / Inventory |
| 3 | `find_unmet_demand` | reads `chat_messages` + `users` + `catalogue` | Boss |
| 4 | `inventory_health` | reads `inventory` + `catalogue` | Inventory |
| 5 | `revenue_exposure` | reads `inventory` + `catalogue` | Accounting |
| 6 | `check_asset_integrity` | reads `catalogue` + `chat_messages` + filesystem | Facilities |
| 7 | `record_ticket_resolution` | **writes** `ticket_resolutions` | Boss |

## Agents — `backend/`

| Agent | Prompt | Authority |
|---|---|---|
| Boss | `prompts/boss.md` | Decides and records. Flags spend for human approval. |
| Inventory | `prompts/inventory.md` | Advises. May recommend a reorder, never commit it. |
| Accounting | `prompts/accounting.md` | Advises. May not authorise spend or forecast revenue. |
| Facilities | `prompts/facilities.md` | Advises. Has no write tool at all. |
| Customer Service | `prompts/customer_service.md` | Drafts replies. A human sends them. |

## API, dashboard

Routes are listed in the API section above. Dashboard is React + Vite + TypeScript in `frontend/`,
served on `localhost:5173`, talking to `localhost:8000`. Design rationale in `output/design.md`.

---

# Safety — addendum from the run of record

The safety section above describes the controls as designed. This records how they behaved in
practice, and one defect the run exposed.

## Defect found: the Boss's own tool calls were not audited

`run_specialist()` instrumented specialist tool calls, but nothing instrumented the Boss's. The
result was that `record_ticket_resolution` — **the only tool in the system that writes** — executed
three times, wrote three rows, and left no `tool_call` record in the audit trail. The decision
records existed; the evidence of who created them did not.

An audit log that omits the single writing tool is missing exactly the wrong thing. `backend/boss.py`
now records the Boss's MCP calls after each run. The three archived runs in `output/audit_trail.json`
predate that fix, so for those runs the `ticket_resolutions` rows (`decided_by = 'Boss'`) are the
corroborating evidence rather than the trail itself.

This is worth stating plainly because it is the failure mode auditing systems actually have: the log
looked complete, and was trusted, while silently excluding the highest-privilege action in the system.

## Controls that held

- **No unverified promise.** Eight `check_stock` calls preceded every product named to a customer.
- **No invented economics.** Accounting refused a payback figure, naming the missing inputs instead.
- **No unapproved spend.** T1 was flagged `needs_human_approval` and no funds moved. Separately,
  the payment route was verified to refuse an agent-named approver, an overdraw, a non-existent
  resolution and a missing memo.
- **Reset is not a cover-up.** `POST /admin/reset` cleared the working database but left all 86
  audit records intact, including the runs whose data it erased.
- **Append-only held.** No record was removed from the trail at any point across nine problems.

## Limits that remain

Restating the gaps a real deployment must close, unchanged by this run:

- No authentication or rate limiting on the MCP server.
- No per-run dollar ceiling — the delegation cap bounds calls, not spend.
- Customer names and emails flow into the audit trail, which must therefore be access-controlled
  and retention-limited.
- `needs_human_approval` is a flag nothing in code blocks on.
- Prompt injection is undefended: `chat_messages.content` is customer-supplied text reaching agent
  context through `find_unmet_demand`.
- **New:** resolving a customer conversation is not the same as fixing the defect that caused it.
  T3 closed without the colour-synonym fix, so the ticket count went down while the underlying
  failure stayed. A real deployment needs the distinction between "customer answered" and "cause
  removed" to be tracked separately, or the system will quietly retire the same bug forever.
