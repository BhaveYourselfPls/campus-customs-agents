# AI Prompts Log — HW 5

Multi-agent shop management system (MCP server + FastAPI backend + React dashboard).
Agents: Boss, Inventory, Accounting, Facilities, Customer Service — full connectivity.
Model: `gpt-6-luna` via Portkey (`PORTKEY_API_KEY` loaded from root `.env`).

---

## Context Prompt — Project Setup

> Context: Multi agent team to run a shop. Will use MCP server, FastAPI Backend, React dashboard.
> Agents have full connectivity. Agents are a Boss, Inventory, Accounting, Facilities, Customer Service.
> Will re-use data.zip file.
> Use Portkey_key_api using GPT-6-luna

**Outcome:** Established architecture and constraints. Verified `HW 5/` empty, root `.env` present,
`Code/mcp_servers/` available for reuse. Flagged that `data.zip` was not found on disk.

---

## Problem 1 — Prompt Log File

> Problem 1: Create AI_prompts.md and keep it updated as we work with each new prompt.
> If there are multiple prompts per problem include a brief description of what was
> missing from the initial prompt response.

**Outcome:** Created this file. Will append every subsequent prompt verbatim, with outcome notes.
For any problem requiring follow-up prompts, a **Gap** note records what the prior response missed.

---

## Problem 2 - Data Setup & Schema Harness

> Problem 2: unzip data.zip from the downloads folder and put it in the HW5 folder.
>
> Open data/campus_customs.db and copy it to data/campus_custums_new.db.
>
> Understand how the 3 open tickets link to other tables.
>
> Start output/harness.md for each table explain what each field means and why it is useful.

**Outcome:** Extracted `~/Downloads/data.zip` into `HW 5/` -> `data/products/` (102 product images),
`data/test_images/`, `data/videos/`. Created `output/harness.md` documenting all 4 tables
(`catalogue`, `inventory`, `users`, `chat_messages`) field by field, with the ticket link path
and per-agent ownership.

**Two discrepancies found and resolved:**

1. **`campus_customs.db` was not in data.zip.** The zip ships only media assets. Located the DB at
   `HW 4/hw4/data/campus_customs.db` and copied it to `HW 5/data/campus_customs.db`, then made the
   working copy `data/campus_custums_new.db` (user's spelling preserved verbatim).
2. **There is no `tickets` table.** No such table exists in the DB and no "ticket" reference exists
   anywhere in the HW4 codebase. Interpreted "the 3 open tickets" as the 3 unresolved customer
   requests in `chat_messages` (failed searches returning `products_json = []`): gym shorts
   (assortment gap), Handsome Dan (vocabulary gap), emerald green hoodie (color-matching gap).
   Assumption is flagged in-line in `harness.md` pending confirmation.

---

## Problem 3 - MCP Server

> Problem 3:
> Create a MCP server in mcp_server/ use FastMCP. We plan to have this interface with the new.db
>
> All agents will use this one MCP server.
>
> Create 3 tools for the MCP server that are useful for handling tickets.
>
> In Output/harness.md list the tools. It should include info on what table the tool reads,
> which ticket it unlocks, and why the tool is right for that ticket.
>
> Create a mcp_server/README.md that explains the MCP servers purpose, the database file it
> uses, and the 3 tools.

**Outcome:** Built `mcp_server/mcp_server.py` (FastMCP, server name `campus-customs-shop`),
reading `data/campus_custums_new.db` read-only via `mode=ro`. Three tools, one per failure layer:
`search_products` (retrieval -> tickets #2, #3), `check_stock` (fulfilment gate -> all three,
decisive for #3), `find_unmet_demand` (assortment -> ticket #1). Added the tools table to
`output/harness.md` and wrote `mcp_server/README.md` + `requirements.txt`.

**Two bugs caught by testing against the live DB before shipping:**

1. **Substring matching produced false hits.** Naive `term in blob` matched "im" (from
   "im looking for gym shorts") inside "trim", so the gym-shorts assortment gap was being
   misclassified as a successful search. Replaced with whole-word regex matching.
2. **Empty `products_json` alone over-counted tickets.** Greetings ("yo") and small talk
   ("this hoodie is cool right") also surface no products, yielding 6 false tickets.
   Now requires the assistant reply to contain an explicit failure phrase, and collapses
   repeat asks from the same customer into one ticket with a `times_asked` count.

Verified end state: `find_unmet_demand()` returns **exactly 3 open tickets**, matching the
3 documented in Problem 2.

**Note:** `fastmcp` is not installed in the active interpreter. Tool logic was verified against
the real database using a minimal FastMCP stub; `pip install -r mcp_server/requirements.txt`
is still required before the server itself can run.

---

## Problem 4 - Callable Tools & Smoke Evidence

> Problem 4
> Make it so we can call tools from here. Save the connection info to .mcp.json in the HW5 folder.
> Test the 3 tools. Save evidence of the tests in output/mcp_smoke.json. Include 1) prompt that
> was asked. 2) tool name 3) tool output (Should have values from the .db file).

**Outcome:** Created `.venv` (uv, Python 3.13.5) and installed `fastmcp 4.1.0`. Wrote `.mcp.json`
registering `campus-customs-shop` over stdio. Wrote `mcp_server/smoke_test.py`, which launches the
server through `.mcp.json` and calls all 3 tools via a real MCP client. Evidence in
`output/mcp_smoke.json`: 6 calls, each recording prompt, tool_name, arguments, and full tool_output
with live DB values.

**Three defects caught and fixed during this problem:**

1. **`find_unmet_demand` crashed through the real client** - `'function' object has no attribute 'fn'`.
   In fastmcp 4.x a decorated tool is not callable as a plain function. Refactored the search body
   into `_search_products()` and made the tool a thin wrapper; the internal reuse now calls the helper.
   This only surfaced because the test went through a real MCP client rather than importing the module.
2. **The "negative case" was not negative** - 2025 Yale vs Harvard T-shirt XXL had 15 units in stock,
   so the test proved nothing. Queried the DB for a genuinely sold-out row and switched to
   `baseball-left-chest-crewneck` / XS, which returns `status: sold_out, can_promise: false`.
3. **A factual error in harness.md** - it claimed "not every product carries all 6 sizes (612 != 102x6)".
   102 x 6 = 612 exactly, so every product does carry all six sizes and `not_carried` never fires on
   today's data. Corrected the harness; the code keeps the distinction defensively.

**Verified results:** 3 tools discovered. Handsome Dan -> 3 matches; emerald green hoodie (in-stock
only) -> 3 matches; gym shorts -> 0 matches with `unmatched_terms: ["gym","shorts"]`; stock gate
returns qty 8 / can_promise true and qty 0 / can_promise false; `find_unmet_demand` -> 3 open tickets.

---

## Problem 5 - PydanticAI Agent Team

> Problem 5
> Build the team using PydanticAI, reference the bots mentioned in the context.
> Put the prompts in backend/prompts/ each agent should have its own .md file. Data types should be
> in backend/models.py and agent files should be in backend/
> Calls should use the portkey_key_api in the root .env calling gpt-5.6-luna.
> Be specific in the agent prompts.
> Add any needed tools to the MCP server.
> The agents should append output/audit_trail.json so that for each loop step there is a sufficient
> audit log. Only append this file, never delete data.
> In output/harness list each agent and tool. Add a safety section, assume this will be used in a
> real business.
> Update mcp_server/README.md file with any new tools

**Outcome:** Five PydanticAI agents on `gpt-5.6-luna` via Portkey. `backend/models.py` (typed
hand-offs), `backend/config.py`, `backend/audit.py`, `backend/specialists.py`, `backend/boss.py`,
`backend/run_team.py`, and five prompts in `backend/prompts/`. Added 4 MCP tools (7 total):
`inventory_health`, `revenue_exposure`, `check_asset_integrity`, `record_ticket_resolution`.
Added Agent Team and Safety sections to `output/harness.md`; updated `mcp_server/README.md`.

**Model name discrepancy, resolved:** three different names were given across prompts
("GPT-6-luna", "got-5.6 luna", "gpt-5.6-luna"). Probed Portkey directly - both `gpt-5.6-luna` and
`gpt-6-luna` respond. Used `gpt-5.6-luna` per the most recent instruction; overridable via MODEL_NAME.

**Three bugs caught by running the team live:**

1. **`MCPServerStdio` does not exist in pydantic-ai 2.55.** The lecture code targets 1.x. Rewrote
   against `MCPToolset` + `StdioTransport`, and pointed it at `.mcp.json` rather than hard-coding
   the path, so the agents and the Claude Code session provably share one server.
2. **`result.usage()` is a property in 2.x, not a method.** This failed inside the specialist
   wrapper, so all four specialists returned "unavailable" low-confidence reports on the first run.
   The error-handling worked as designed - the Boss still produced decisions and said it had
   discounted the unavailable findings - but the answers were far weaker.
3. **OneDrive blocked the atomic audit write** (`WinError 5` on `os.replace`), losing the whole
   trail on run 1. Added bounded retries then a direct-write fallback: losing an audit record is
   worse than a non-atomic write.

**Verified live run:** 38 audit records, 22 MCP tool calls across 4 specialists, 3 decisions, 3
escalations, 2 flagged for human approval. No credential present anywhere in the trail.

**Observation worth noting:** the Boss did not consult Facilities on this run. Nothing in the three
tickets touches assets or data integrity, so that is defensible routing rather than a defect - but
it means Facilities is currently unexercised by the default question.

---

## Problem 6 - Expected Behaviour Desk Page

> Problem 6:
> Write down what you expect the team to do on the open tickets. Build output/desk_tickets.html,
> this should be a page you can double click with 1 tab per ticket. Add empty Cash and Reflection
> tabs for later problems.
> On the tab for each ticket, create an Expected section (There will be an Actual section later).
> Write 1) Who the Bos will call first and why 2) All agent delegations expected (outside of the
> Boss), 3) What tools they will likely use in the Expected section.

**Outcome:** Built `output/desk_tickets.html` - a single self-contained file, no build step, opens
by double-click. Five tabs: one per ticket, plus empty Cash and Reflection placeholders. Each ticket
tab carries an Expected section (first call + why, delegations, tools, expected outcome, and the
specific failure mode to watch) and an empty Actual section. Black/white/blue, per AGENTS.md.

**Disclosure on "Expected":** Problem 5 already included one live team run, so these predictions are
written after observing a run rather than blind. They are derived from the prompt routing rules and
stated as design intent, but they are not an uncontaminated forecast. Flagged rather than presented
as a clean prediction.

---

## Problem 7 - FastAPI Backend

> Problem 7:
> Create the backend backend/main.py use FastAPI and add routes to:
> 1. Return the 3 tickets and their status (Open, Resolved)
> 2. Run agent team on a given ticket ID
> 3. Return recent agent actions, what they said, what tools were used
> 4. Approve payment/purchase after a human has approved.
> 5. Return current checking balance from cash_accounts
> 6. Reset the database to original values.
> From backend/ start the server with uvicorn main:app --reload --port 8000
> In output/harness.md, list each out in a single line (URL, what it does)

**Outcome:** Built `backend/main.py` (FastAPI, 8 routes) and `backend/shop_data.py` (direct DB
access for the operator layer). Added the route table to `output/harness.md`. Server verified live
on port 8000.

**`cash_accounts` did not exist** - the prompt referenced a table absent from the database. Created
it along with `cash_transactions` (append-only, `balance_after` stamped per row so the balance is
re-derivable), seeded at $25,000 opening checking balance, created idempotently at startup and
re-seeded after reset.

**Design decision worth stating:** money movement is deliberately kept out of the MCP server. Agents
reach the shop only through MCP, which is read-only apart from recording decisions; `POST
/approvals/{id}/pay` is an operator route with no agent-facing tool behind it. An agent therefore
cannot pay for anything even if it decides to.

**Verified live, including the refusals:**

- `GET /tickets` -> 3 tickets; status correctly derived from recorded resolutions, not agent prose.
- `POST /tickets/T2-handsome-dan/run` -> 12 audit steps, 1 delegation to Customer Service,
  tools `find_unmet_demand` x1, `search_products` x1, `check_stock` x5. Ticket flipped Open ->
  Resolved. This matches the Problem 6 prediction exactly: single-delegation to Customer Service,
  repeated `check_stock` calls before naming any product, no spend.
- `POST /approvals/2/pay` refused all four guard cases: agent-named approver ("Boss"), overdraw
  ($999,999 vs $25,000), nonexistent resolution (9999), and accepted a valid human approval
  ($1,800 -> balance $23,200).
- `POST /admin/reset` -> cleared 7 resolutions and 1 transaction, tickets returned to Open, checking
  back to $25,000, and the audit trail still held all 38 records.

**Observation:** on the T2 run Customer Service returned `needs_human: false`. Its prompt says to set
it true when a reply would commit the shop. Drafting a reply that a human must still send is a
borderline case, but the stricter reading is the safer one - worth tightening if this were live.

---

## Problem 8 - React Dashboard

> Problem 8: Create the frontend dashboard in frontend/
> Use React + Vite + TypeScript.
> The dashboard should: 1. List all tickets 2. Let you pick a ticket and start a agent team on it
> 3. SHow what each agent is saying/doing 4. Mark a ticket resolved 5. SHow a summary of what each
> agent did 6. Let a human approve a transaction 7. Show checking balance
> Make the dashboard look good, modern, and slick, with some fun eastereggs.
> It should speak to the backend at localhost:8000
> Allow Vite page origin(localhost:5173) to call those routes.
> Start the dashboard with npm run dev
> Write output/design.md with what you chose the the design.
> Be creative

**Outcome:** Scaffolded `frontend/` (Vite React-TS). Built `src/App.tsx`, `src/api.ts`,
`src/types.ts`, `src/index.css`. Wrote `output/design.md`. Typecheck and production build both
clean; CORS verified by preflight from the Vite origin.

**Backend gap found:** requirement 4 ("mark a ticket resolved") had no route - ticket status was
derived from `ticket_resolutions` with no way to write one by hand. Added
`POST /tickets/{id}/resolve` plus `shop_data.record_resolution()`, using the same append-only
contract as the agents' own tool, and added it to the harness route table.

**Design decisions worth noting:**

- The live feed polls `/actions`, i.e. it reads the *same append-only audit trail an auditor would
  read*. No separate in-memory event stream that could drift from the record.
- The agent stage always renders all five agents, even when only one runs, so under- and
  over-delegation are both visible. On the Handsome Dan ticket you can see at a glance that
  Inventory, Accounting and Facilities were not consulted.
- The approval form surfaces the backend's own refusal text rather than a generic failure, so
  approving as "Boss" shows the actual rule being enforced.
- "Mark resolved" deliberately requires a rationale rather than being one click, because status is
  derived from the record, not a flag.

**Easter eggs:** click the bulldog logo (barks; 5 clicks sends Handsome Dan trotting across the
screen), type "handsome" anywhere, Konami code toggles Boola Boola hue-rotate, and the rotating
waiting messages are all true statements about the agent prompts. All four sit outside the data
path - none can alter a ticket, move money, or change what agents see.

**Verified:** `POST /tickets/T3-emerald-green-hoodie/resolve` recorded resolution #2 and flipped the
ticket to Resolved; an empty rationale is rejected with 422.

**Not visually verified:** the in-app browser preview is not enabled on this install, so I confirmed
the dashboard via typecheck, production build, served HTML and live API calls - not by looking at
the rendered page. Worth a visual pass.

---

## Problem 9 - Run of Record

> Problem 9: reset the working database (use the original.db file to overwrite the new.db file).
> Then run all 3 tickets on the board until they are resolved.
> Open output/desk_tickets.html from problem 6. Fill the Action section based on the run.
> (WHo worked, what was delegated, what tools). Dont change the Expected section.
> In the Cash tab of output/desk_tickets.html itemize: 1. Starting balance 2. How cash changed for
> each ticket and why 3. Ending checking balance. SHould match cash_accounts.
> Cash math is important, it shouldnt be wrong.
> Save: 1. Output/resolved_tickets.json ... 2. output/resolved_board.html ...
> Append real runs to the audit trail.
> Complete output/harness.md to cover tables, MCP tools, the agents, API routes, dashboard, and safety.

**Outcome:** Reset to baseline, ran all 3 tickets to Resolved (36 audit steps, 17 MCP tool calls,
appended to the trail - now 86 records total). Filled the Actual sections and Cash tab of
`desk_tickets.html`, verified the Expected sections are byte-identical to before. Wrote
`output/resolved_tickets.json` and `output/resolved_board.html` with four real screenshots in
`output/shots/`. Completed `output/harness.md`.

**Cash: $25,000.00 opening - $0.00 debits = $25,000.00 closing**, reconciling exactly with
`cash_accounts.balance`, zero rows in `cash_transactions`. Nothing moved because the only ticket
that could cost money (T1 gym shorts) was one the team recommended *against* buying. A zero is the
correct answer here, not a missing one; the approval path was exercised and verified separately in
Problem 7.

**Audit defect found and fixed:** the Boss's own MCP tool calls were never instrumented - only
specialists were. `record_ticket_resolution`, the one tool that writes, ran three times and left no
`tool_call` record. Fixed in `backend/boss.py`; the three archived runs predate the fix, so their
corroborating evidence is the `ticket_resolutions` rows rather than the trail. Documented in the
harness safety section, because an audit log that silently omits the highest-privilege action is the
failure mode auditing systems actually have.

**Dashboard gap found and fixed:** a page reload lost the run - a resolved ticket rendered with every
agent idle. Added `GET /tickets/{id}/history`, which replays the last run from the audit trail, and
wired the board to it. The agent stage now shows "reported" vs "not consulted" from real history,
which is what makes the screenshots meaningful.

**All three Problem 6 predictions held.** T1 went to Inventory then Accounting, both escalating;
T2 and T3 each took a single delegation to Customer Service. None of the three predicted failure
modes occurred.

**Honest residual:** T3 closed without fixing the colour-vocabulary gap that caused it, so the next
customer asking for "emerald" fails identically. The ticket count went down; the bug did not.

---

## Problem 10 - Reflection Tab

> Problem 10
> in output/desk_tickets.html complete the reflection tab.
> Be detailed and thorough when answering.
> 1. How would you evaluate the performance of the agents on each ticket and why?
> 2. For each ticket, how did Actual compare to the Expected plan?
> 3. What would have been simpler as one agent with tools and why?
> 4. Describe 3 new problems campus customs might face that this agent could solve.
> 5. Describe 3 new problems that this agent team can NOT solve and explain what tools/agents
> would be needed to solve them
> Tie all answers to this app and the 3 tickets, use the ticket tabs and cash tag as evidence.

**Outcome:** Completed the Reflection tab - 5 sections, 5 tables, 10 sub-sections, graded per
ticket (T1 A-, T2 A, T3 A-). Verified the Expected sections, Actual sections and Cash tab are all
byte-identical to before, and that all 5 tabs still switch. Render-checked with Playwright.

**Grounded in run-of-record evidence throughout**, not generic commentary: per-ticket wall times
and token counts from the audit trail (T1 38.5s/11,941; T2 7.4s/13,954; T3 27.9s/11,774), quoted
findings with their cited tool output, the 8 check_stock calls, the 15-of-15 evidence rate, and the
Cash tab's $25,000 -> $25,000 reconciliation.

**The sharpest conclusions drawn:**

- **T2 and T3 should have been one agent.** Each resolved with a single delegation, so the Boss
  contributed only a forwarding hop. T2 burned the *most* tokens of the three runs (13,954) on the
  *simplest* ticket, because Boss and Customer Service each paid to load the same context. The
  five-agent structure earned its keep only on T1, where Inventory and Accounting refused for
  genuinely different reasons and produced two independent escalations.
- **Splitting the work split the insight.** Customer Service saw `unmatched_terms=["emerald"]` and
  the Boss decided the customer reply; neither owned the synonym fix, so it fell between them. A
  single agent holding both views would likely have caught it.
- **Accounting padded on T1.** Two of its four findings ($344,168 shelf value; 145 sold-out rows)
  were correctly cited and irrelevant to gym shorts - about half its output did not bear on the
  question.
- **A permanent blemish in the record:** the Boss's T2 rationale contains a garbled fragment
  ("five available bulldog/m mascot products"), now unfixable in `ticket_resolutions` row #2 because
  that table is append-only by design. Can only be superseded, never tidied.
- **Facilities has still never been consulted** across any ticket - the only agent with zero
  exercise, which is why the pre-Harvard-Yale asset sweep is proposed as work it could do today.
- **Overall verdict: trustworthy and inert.** Every control that prevents damage held; nothing that
  would improve the shop fired, because no tool can change the shop. Three tickets are closed in the
  database and open in the customer's inbox.

---

## Problem 11 - Public GitHub Repo

> Problem 11
> Push the code to a public github repo.
> Put a link to the repo in output/github_url.txt
> Ensure the .env is not included.
> Confirm all the expected files from the picture are included.
> The README should explain copying the original .db to the working copy when a clean run is
> needed, starting the MCP server, start FastAPI and React dashboard, and resetting the .db.

**Outcome:** Pushed to https://github.com/BhaveYourselfPls/campus-customs-agents (public, `main`,
167 files). Link written to `output/github_url.txt`. Wrote root `README.md`, `.gitignore`,
`.env.example` and a consolidated `requirements.txt`. Verified all 25 expected files from the
picture are present on the remote, plus 102 product images and 21 frontend files.

**Two renames to match the picture exactly:**

1. `data/campus_custums_new.db` -> `data/campus_customs_new.db`. The original spelling was a typo
   in the Problem 2 prompt that I had preserved verbatim; the picture uses the correct spelling.
   Updated every reference across code, configs, docs and output artifacts.
2. `mcp_server/mcp_server.py` -> `mcp_server/server.py`, including `.mcp.json` and the
   `import mcp_server` in `backend/shop_data.py`.

`AI_prompts.md` was deliberately left with the old names - it is a historical log of what was
actually asked and done, and rewriting it would falsify the record.

**Two fixes made for the repo to be genuinely usable by someone else:**

1. **`.mcp.json` contained machine-specific absolute paths** pointing at my own venv and OneDrive
   folder - useless in a clone. Rewritten to a portable `"python"` + `mcp_server/server.py`, with
   `backend/config.py` and `mcp_server/smoke_test.py` resolving both against the running
   interpreter and the actual checkout at launch.
2. **`requirements.txt` floors were dangerously loose.** `pydantic-ai-slim>=1.0.0` would install
   1.x, which exposes `MCPServerStdio` rather than the `MCPToolset`/`StdioTransport` API this code
   uses - a clone would have failed at import. Pinned to the versions actually verified
   (pydantic-ai 2.55, fastmcp 4.1), with a comment explaining why the floors are not cosmetic.

**Security verified three ways:** `.env` is gitignored and absent from the staged set; a grep for
the live key prefix across all tracked files returns nothing; and the remote 404s on `/contents/.env`.
`.venv/`, `node_modules/` and `.claude/` are all excluded.

**Verified by cloning fresh into a temp directory:** both databases open with 102 catalogue rows,
and `smoke_test.py` drove all 7 MCP tools successfully from the clone with no edits.

**Note:** `data/campus_customs_new.db` ships in its post-run state (8 tables, 3 recorded
resolutions), matching `output/resolved_tickets.json`. The README explains copying the baseline
over it for a clean run.

---
