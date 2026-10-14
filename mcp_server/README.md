# Campus Customs Shop MCP Server

One MCP server, shared by the whole agent team.

## Purpose

The shop is run by five agents — **Boss, Inventory, Accounting, Facilities, Customer Service** — and they are fully connected, so any of them can end up answering a question about stock, price, or an open ticket. If each agent queried the database its own way, they would contradict each other: one promises a hoodie that another knows is sold out.

This server is the fix. It is the **single source of truth** between the agents and the shop data. Every agent calls the same three tools, so every agent gets the same answer, with the same stock gate applied and the same vocabulary expansion. The agents hold the judgment; the server holds the facts.

Built with [FastMCP](https://github.com/jlowin/fastmcp). Six of the seven tools are **read-only** (`mode=ro`), so no agent can corrupt the shop data mid-conversation. The seventh writes only append-only decision records into its own table.

## Database

**`../data/campus_customs_new.db`** — the working copy of the Campus Customs SQLite database.

The pristine original stays at `../data/campus_customs.db` and is never touched, so there is always a rollback baseline. Four tables are in play:

| Table | Rows | What the server uses it for |
|---|---|---|
| `catalogue` | 102 | Product identity, price, colors, search tags, image path |
| `inventory` | 612 | Per-size stock; the gate on what can be promised |
| `users` | 4 | Attaching a name and email to a ticket |
| `chat_messages` | 18 | The record of what customers asked and what the shop answered |

Field-by-field documentation lives in [`../output/harness.md`](../output/harness.md).

Two facts shape every tool here:

- **24% of inventory rows sit at quantity 0.** Being in the catalogue and being shippable are different claims.
- **A missing inventory row ≠ a zero row.** Missing means "we never carried that size"; zero means "carried but sold out". The tools report these separately.

## The seven tools

Tools 1-3 handle the open tickets. Tools 4-7 serve the agent team.

### 1. `search_products(query, in_stock_only=False, limit=10)`

Searches the catalogue **the way a customer actually talks**, not the way the database is indexed.

Customer words are expanded into catalogue vocabulary before matching — `"Handsome Dan" → "bulldog"`, `"emerald" → "green"`, `"tee" → "t-shirt"` — then every product is scored across name (×5), search tags (×4), colors (×3), garment type (×3), and description (×1). Matching is whole-word, so `"im"` no longer hits `"trim"`. Results come back with price, image path, and live per-size stock already attached.

Returns `terms_used` so the caller can see which synonyms fired, and `unmatched_terms` when nothing hits — an unmatched term is a genuine assortment gap worth escalating to Inventory, not a search bug to retry.

### 2. `check_stock(product_id, size=None)`

The authoritative availability check, and the gate every agent must pass before promising a customer anything.

Returns `can_promise` as a single boolean to act on, plus a `status` that distinguishes `in_stock`, `sold_out`, `not_carried`, and `unknown_product`. Flags `low_stock` at 5 units or fewer so Inventory sees a reorder coming before it becomes a stockout.

### 3. `find_unmet_demand(limit=20)`

Mines the chat log for things customers asked for and did not get, then classifies each one.

It finds assistant replies that surfaced no products **and** explicitly said the search struck out — greetings and small talk also surface no products, so an empty result alone is not a ticket. Each failed ask is re-run through today's search and labelled:

- **`fixable_by_search`** — stock exists now, so the original failure was a vocabulary or color defect. Owner: Customer Service.
- **`true_assortment_gap`** — nothing matches even after synonym expansion. That is a buying decision. Owner: Inventory.

Repeat asks from the same customer that resolve the same way collapse into one ticket with a `times_asked` count, because a customer rephrasing is one problem, not several.

Run against the current database it returns exactly **3 open tickets**: 1 true assortment gap (gym shorts) and 2 search defects (Handsome Dan, emerald green hoodie).

### 4. `inventory_health(low_stock_threshold=5, limit=25)`

Inventory's standing view of the shelf: how many product-size rows are sold out, how many are close, total units on hand, and which products have nothing available in any size. `limit` caps the detail lists, never the counts.

Against the current database: 612 product-size rows, 145 sold out (23.7%), 115 at or below 5 units, 5,920 units on hand.

### 5. `revenue_exposure(limit=15)`

Accounting's view, and three figures that are easy to confuse, reported separately: `stock_at_retail` (units x price, what the shelf is worth), `sold_out_exposure` (the price of every sold-out row, unavailable until restocked), and `fully_sold_out_value`.

**All figures are retail value, not realised revenue.** There is no sales or order table in this database, so nothing here is a forecast, and the tool says so in its own `basis` field. Current shelf value: $344,168 across 5,920 units.

### 6. `check_asset_integrity(limit=25)`

Facilities' view. Verifies the two links SQLite does not enforce, because they are plain strings rather than foreign keys and will rot silently: `catalogue.image_file_path` to a real file under `data/`, and `chat_messages.products_json` to a real `catalogue.product_id`. Also reports orphan image files and catalogue entries with no inventory rows.

Current state: all 102 products check clean.

### 7. `record_ticket_resolution(ticket_ref, decision, rationale, decided_by, owner, product_ids=None)`

**The only tool that writes.** Inserts a row into `ticket_resolutions`, creating the table on first use.

It is strictly append-only: rows are never updated or deleted, so a wrong decision is corrected by recording a new one rather than erasing the old. `decided_by` must name the agent and `rationale` must explain why - a resolution with no reasoning is rejected rather than stored.

## Running it

Install dependencies:

```bash
pip install -r requirements.txt
```

Run over stdio (how agents normally attach):

```bash
python mcp_server.py
```

Run over HTTP at `http://127.0.0.1:8002/mcp`:

```bash
python mcp_server.py --http
```

`--host` and `--port` override the defaults. The server exits immediately with a clear error if the database file is missing.

## Files

```
mcp_server/
├── mcp_server.py      # FastMCP server, 7 tools
├── smoke_test.py      # drives every tool through a real MCP client
├── requirements.txt   # fastmcp
└── README.md          # this file
```

## Who calls what

| Tool | Boss | Inventory | Accounting | Facilities | Customer Service |
|---|---|---|---|---|---|
| `search_products` | | x | x | x | **x** |
| `check_stock` | | **x** | | | **x** |
| `find_unmet_demand` | **x** | | | | x |
| `inventory_health` | | **x** | x | x | |
| `revenue_exposure` | | | **x** | | |
| `check_asset_integrity` | | | | **x** | |
| `record_ticket_resolution` | **x** | | | | |

Bold marks the agent that owns the tool; the rest may call it to verify a neighbour's claim.
