# Dashboard Design

React + Vite + TypeScript in `frontend/`. Talks to the FastAPI backend at `localhost:8000`;
Vite serves the page on `localhost:5173`, which the backend's CORS list already allows.

```bash
cd frontend && npm run dev
```

---

## The problem the layout solves

This dashboard watches **agents spending real money against a real database**. That makes it a
different design problem from a normal CRUD app. The operator needs three questions answered at a
glance, continuously:

1. What is the team working on right now?
2. What did it actually do — not what it claims it did?
3. How much money is left?

Everything below follows from those three.

## Layout: a fixed rail, a scrolling stage

A **324px dark rail** holds the ticket list and the checking balance. Both are permanently visible
and never scroll out of view. The main pane scrolls.

The balance sits in the rail rather than in a card because it is the number that must never be
hidden. An operator approving a $1,800 purchase should not have to scroll to remember what is in the
account. It is the only figure in the interface that is always on screen.

Tickets live in the rail for the same reason: the open/resolved count is the shop's actual workload,
and burying it behind a tab would make it something you check rather than something you see.

## Colour: black, white, blue — and blue means one thing

Per the project palette. The constraint turned out to be useful rather than limiting, because it
forces blue to carry a single meaning: **blue is attention**. Selected ticket, active agent, primary
action, live tool call. Nothing decorative is blue.

Two colours break the palette deliberately, and only where ambiguity would be dangerous:

- **Amber** for `needs approval` and escalations. These are the states where an agent is saying "I
  will not decide this" — the one thing an operator must never skim past. Rendering them in the same
  blue as everything else would hide them in plain sight.
- **Green**, used sparingly, for `Resolved` and a successful approval. Completion reads as green
  almost pre-attentively; fighting that costs clarity for no gain.

Red appears only on a debit amount and an error. Money leaving the account should look like money
leaving the account.

## The agent stage

Five cards, one per agent, in a fixed row. Each has an emoji face, a name, and a status line.

The row is **always five cards**, even when only one agent runs. That is the point: when the Boss
delegates only to Customer Service on the Handsome Dan ticket, you can see at a glance that
Inventory, Accounting and Facilities *were not consulted*. A list that only rendered active agents
would hide a routing decision that is genuinely worth noticing — over-delegation and
under-delegation are both failure modes, and neither is visible unless the full roster is.

The active agent bobs gently and gets a sweeping underline. The animation is slow (1.1s) on purpose —
a fast pulse reads as an alarm, and nothing here is an emergency.

## The live feed

A full team loop takes tens of seconds against a real model. Rather than block on a spinner, the
dashboard polls `/actions` every 1.5 seconds and streams the audit trail in as it is written.

This is the design decision I am happiest with: **the feed reads the same append-only audit trail
that an auditor would read.** There is no separate in-memory event stream that could drift from the
record. If the feed says `check_stock()` ran five times, the trail says so too, because they are the
same data. A dashboard that showed a prettier story than the audit log would be worse than no
dashboard.

Each row shows the actor, the step type, and the tool in monospace with parentheses — `check_stock()`
— because tool calls are the verifiable part of what an agent did, and they should look like code
rather than prose.

The feed is baselined at run start, so you see this run, not the history.

## Waiting states

Rotating messages during a run, changing every 3.2s:

> "Counting bulldogs in the catalogue…" · "Nobody is promising anything unverified…" ·
> "Accounting is refusing to forecast revenue…"

They are jokes, but they are *true* jokes — each one describes a real constraint in the agent
prompts. The wait is long enough that honest content beats a generic "Loading…", and it teaches the
system's rules to whoever is watching.

## Approvals: the form argues with you

The approval card is deliberately not a one-click button. It requires a resolution, an amount, a
named human, and a memo — and the backend rejects an approver named after any of the five agents.

The frontend surfaces the backend's **own refusal text** rather than a generic "Request failed".
When you try to approve as "Boss", you see *"approved_by must be a human. Agents cannot approve their
own spend."* The control is more legible when the interface explains itself in the words of the rule
it is enforcing.

The card also degrades honestly: with no recorded resolution it says so and offers no form, because
money should not be movable against a decision nobody wrote down.

## Resolving a ticket

"Mark resolved" prompts for a decision, a rationale, and who is closing it. It could have been a
single click, and it is not.

Status in this system is **derived**, never flagged: a ticket is Resolved because a resolution row
exists, not because someone toggled a field. Closing one therefore means writing down why — which is
what makes the status defensible three months later. The friction is the feature.

## Easter eggs

Four, all harmless and none interfering with the work:

1. **Poke the bulldog.** Click the logo — it pops and barks a speech bubble. Five clicks and Handsome
   Dan trots across the bottom of the screen and back.
2. **Type `handsome` anywhere.** Same dog, no clicking required. A nod to Ticket 2, where the shop
   failed to find him because the catalogue only knew "bulldog".
3. **The Konami code** (↑↑↓↓←→←→BA) toggles *Boola Boola mode* — a slow hue-rotate across the whole
   page. Toggle it again to stop.
4. **The waiting messages** themselves, which most people will read as flavour and a few will
   recognise as the actual prompt constraints.

They all live outside the data path. None can change a ticket, move money, or alter what the agents
see — an easter egg that could affect a business record would be a bug wearing a costume.

## Typography and motion

System font stack, 15px base, 1.55 line height. Monospace (`SF Mono`/`JetBrains Mono`/Consolas) for
anything machine-generated: ticket ids, run ids, tool names, evidence strings, amounts. The split is
semantic — if a human wrote it, it is in the sans; if the system produced it, it is in the mono, so
you can tell at a glance which is which.

Numbers use `tabular-nums` so the balance does not jitter when it changes.

Motion is short and eased (0.14–0.3s), except the two "something is happening" loops which are
slower. Transitions are on `transform` and `opacity` where possible. Nothing animates on load — the
page should feel settled, not performed.

## What I deliberately left out

- **No charts.** There is no sales data to chart. A revenue graph here would be a lie with axes, and
  Accounting's own prompt forbids producing one.
- **No websockets.** Polling the audit trail is simpler, and it guarantees the UI and the auditable
  record cannot disagree. A socket stream would be a second source of truth.
- **No optimistic updates.** After a run, a resolve, or a payment, the dashboard re-fetches from the
  backend. Showing a state the server has not confirmed is the wrong trade when the state is money.
- **No dark mode.** Two complete palettes would have meant two colour systems to keep honest, and
  the rail already supplies the dark anchor the layout needs.
