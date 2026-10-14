"""Campus Customs shop MCP — shared tool server for the multi-agent team.

One server, five consumers: Boss, Inventory, Accounting, Facilities, Customer Service.
All agents call these same tools so that every answer comes from one source of truth.

Reads (read-only) from ../data/campus_customs_new.db.

Run from this folder (stdio):  python mcp_server.py
Run (HTTP):                    python mcp_server.py --http
HTTP URL:                      http://127.0.0.1:8002/mcp
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = ROOT / "data" / "campus_customs_new.db"

mcp = FastMCP("campus-customs-shop")

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL"]

# The catalogue indexes the mascot as "bulldog", never "Handsome Dan" — ticket #2.
# Colors are free text, so "emerald"/"forest" never match "green" — ticket #3.
SYNONYMS: dict[str, list[str]] = {
    "handsome dan": ["bulldog", "mascot", "dan"],
    "mascot": ["bulldog", "handsome dan"],
    "emerald": ["green"],
    "forest": ["green"],
    "kelly": ["green"],
    "crimson": ["red"],
    "maroon": ["red"],
    "burgundy": ["red"],
    "royal": ["blue"],
    "navy": ["navy blue", "blue"],
    "charcoal": ["gray", "grey"],
    "heather": ["heather gray", "gray"],
    "grey": ["gray"],
    "gray": ["grey"],
    "sweatshirt": ["crewneck", "hoodie", "pullover"],
    "sweater": ["fleece", "pullover"],
    "jumper": ["sweater", "fleece", "pullover"],
    "pullover": ["hoodie", "crewneck", "quarter-zip"],
    "tee": ["t-shirt"],
    "tshirt": ["t-shirt"],
    "shirt": ["t-shirt"],
    "zip": ["quarter-zip", "full-zip"],
    "the game": ["harvard", "rivalry"],
}

# Words that carry no retrieval signal — dropped before matching.
STOPWORDS = {
    "a", "an", "the", "any", "some", "with", "on", "it", "of", "for", "and",
    "or", "me", "you", "your", "got", "have", "has", "do", "does", "is",
    "are", "want", "looking", "show", "find", "something", "anything",
    "bright", "dark", "light", "nice", "cool", "yale",
    "im", "iwth", "well", "how", "about", "what", "whats", "that", "this",
    "right", "yo", "hey", "hi", "please", "can", "could", "would", "there",
}

# Phrases the shop uses when a search came back empty. Used to tell a genuine
# failed lookup apart from ordinary chit-chat that also surfaced no products.
FAILURE_MARKERS = (
    "couldn't find", "could not find", "couldnt find",
    "didn't find", "did not find", "didnt find",
    "couldn't pull up", "could not pull up", "couldnt pull up",
    "no matches", "wasn't able to find", "unable to find",
    "don't have", "do not have",
)


def _connect() -> sqlite3.Connection:
    """Open the shop DB read-only so no agent can corrupt it mid-conversation."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, drop stopwords."""
    words = re.findall(r"[a-z0-9\-]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _expand(query: str) -> list[str]:
    """Turn a customer phrase into the terms the catalogue actually uses.

    Checks multi-word synonyms ("handsome dan") before single words, so the
    mascot lookup survives tokenization.
    """
    low = query.lower()
    terms: list[str] = []
    for phrase, alts in SYNONYMS.items():
        if " " in phrase and phrase in low:
            terms.extend(alts)
    for word in _tokenize(query):
        terms.append(word)
        terms.extend(SYNONYMS.get(word, []))
    # de-duplicate, preserve order
    return list(dict.fromkeys(terms))


def _normalize(text: str) -> str:
    """Lowercase and flatten curly apostrophes, which the chat log uses."""
    return text.lower().replace("’", "'").replace("‘", "'")


def _contains(blob: str, term: str) -> bool:
    """Whole-word containment.

    Plain substring matching produced false hits ("im" inside "trim"), which
    made genuine assortment gaps look like successful searches.
    """
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", blob) is not None


def _sizes_for(conn: sqlite3.Connection, product_id: str) -> dict:
    rows = conn.execute(
        "SELECT size, quantity FROM inventory WHERE product_id = ?", (product_id,)
    ).fetchall()
    by_size = {r["size"]: r["quantity"] for r in rows}
    return {
        "sizes_in_stock": [s for s in SIZE_ORDER if by_size.get(s, 0) > 0],
        "sizes_sold_out": [s for s in SIZE_ORDER if s in by_size and by_size[s] == 0],
        "sizes_not_carried": [s for s in SIZE_ORDER if s not in by_size],
        "total_units": sum(by_size.values()),
    }


# --------------------------------------------------------------------------
# Tool 1 — search_products
# --------------------------------------------------------------------------
def _search_products(
    query: str,
    in_stock_only: bool = False,
    limit: int = 10,
) -> dict:
    """Implementation of the catalogue search.

    Kept separate from the tool wrapper so find_unmet_demand can reuse it
    directly — a decorated tool is not reliably callable as a plain function.
    """
    terms = _expand(query)
    if not terms:
        return {"query": query, "terms_used": [], "match_count": 0, "matches": []}

    with _connect() as conn:
        products = conn.execute(
            """SELECT product_id, name, garment_type, description, colors,
                      search_tags, image_file_path, price FROM catalogue"""
        ).fetchall()

        scored = []
        hit_terms: set[str] = set()
        for p in products:
            # Weighted fields: a tag hit means more than a prose hit.
            fields = {
                "name": (p["name"].lower(), 5),
                "tags": (p["search_tags"].lower(), 4),
                "colors": (p["colors"].lower(), 3),
                "type": (p["garment_type"].lower(), 3),
                "desc": (p["description"].lower(), 1),
            }
            score = 0
            matched: list[str] = []
            for term in terms:
                for blob, weight in fields.values():
                    if _contains(blob, term):
                        score += weight
                        matched.append(term)
                        hit_terms.add(term)
                        break
            if score:
                scored.append((score, p, sorted(set(matched))))

        scored.sort(key=lambda row: (-row[0], row[1]["price"]))

        matches = []
        for score, p, matched in scored:
            stock = _sizes_for(conn, p["product_id"])
            if in_stock_only and not stock["sizes_in_stock"]:
                continue
            matches.append(
                {
                    "product_id": p["product_id"],
                    "name": p["name"],
                    "garment_type": p["garment_type"],
                    "price": p["price"],
                    "colors": json.loads(p["colors"]),
                    "image_file_path": p["image_file_path"],
                    "matched_terms": matched,
                    "relevance": score,
                    **stock,
                }
            )
            if len(matches) >= limit:
                break

    return {
        "query": query,
        "terms_used": terms,
        "unmatched_terms": [t for t in terms if t not in hit_terms],
        "in_stock_only": in_stock_only,
        "match_count": len(matches),
        "matches": matches,
    }


@mcp.tool
def search_products(
    query: str,
    in_stock_only: bool = False,
    limit: int = 10,
) -> dict:
    """Search the catalogue the way a customer actually talks.

    Expands the customer's words into the vocabulary the catalogue really
    uses before matching ("Handsome Dan" -> "bulldog", "emerald" -> "green",
    "tee" -> "t-shirt"), then scores every product on name, description,
    search_tags, colors and garment_type. Returns products with price, image
    and live per-size stock attached.

    Use this for any "do you have ...?" question. Set in_stock_only=True
    before promising anything to a customer.

    Returns matches plus `terms_used`, so the caller can see which synonyms
    fired, and `unmatched_terms` when nothing hits — that is a real
    assortment gap worth escalating, not a search failure.
    """
    return _search_products(query, in_stock_only=in_stock_only, limit=limit)


# --------------------------------------------------------------------------
# Tool 2 — check_stock
# --------------------------------------------------------------------------
@mcp.tool
def check_stock(product_id: str, size: str | None = None) -> dict:
    """Authoritative stock check for one product, optionally one size.

    This is the gate every agent must pass before promising a customer
    anything. 24% of inventory rows sit at quantity 0, so "it's in the
    catalogue" and "we can ship it" are different claims.

    Distinguishes the two ways an item can be unavailable:
      - `sold_out`      - the size is carried but quantity is 0
      - `not_carried`   - no row exists; we never stocked that size

    Returns `can_promise` as the single boolean an agent should act on.
    """
    with _connect() as conn:
        p = conn.execute(
            """SELECT product_id, name, garment_type, price, colors, image_file_path
               FROM catalogue WHERE product_id = ?""",
            (product_id,),
        ).fetchone()
        if p is None:
            return {
                "product_id": product_id,
                "found": False,
                "can_promise": False,
                "status": "unknown_product",
                "note": "No such product_id in catalogue. Use search_products first.",
            }

        rows = conn.execute(
            "SELECT size, quantity FROM inventory WHERE product_id = ?", (product_id,)
        ).fetchall()
        by_size = {r["size"]: r["quantity"] for r in rows}
        stock = _sizes_for(conn, product_id)

        base = {
            "product_id": p["product_id"],
            "found": True,
            "name": p["name"],
            "garment_type": p["garment_type"],
            "price": p["price"],
            "colors": json.loads(p["colors"]),
            "image_file_path": p["image_file_path"],
            **stock,
        }

        if size is None:
            return {
                **base,
                "can_promise": bool(stock["sizes_in_stock"]),
                "status": "in_stock" if stock["sizes_in_stock"] else "sold_out",
            }

        size = size.upper()
        if size not in by_size:
            return {
                **base,
                "size": size,
                "quantity": 0,
                "can_promise": False,
                "status": "not_carried",
                "note": f"We have never stocked {size} in this product.",
            }
        qty = by_size[size]
        return {
            **base,
            "size": size,
            "quantity": qty,
            "can_promise": qty > 0,
            "status": "in_stock" if qty > 0 else "sold_out",
            "low_stock": 0 < qty <= 5,
        }


# --------------------------------------------------------------------------
# Tool 3 — find_unmet_demand
# --------------------------------------------------------------------------
@mcp.tool
def find_unmet_demand(limit: int = 20) -> dict:
    """Mine the chat log for things customers asked for and did not get.

    Walks chat_messages for assistant replies that surfaced no products
    (`products_json` empty or null) and pairs each with the customer message
    that triggered it. Then re-runs every one of those asks through today's
    search to classify it:

      - `fixable_by_search` - stock exists now; the original failure was a
        vocabulary or color-matching defect, not a buying gap.
      - `true_assortment_gap` - nothing in the catalogue matches even after
        synonym expansion. This is a purchasing decision, not a search fix.

    This is the evidence base for what to buy next and which search defects
    to close. Returns per-ticket detail plus counts by classification.
    """
    with _connect() as conn:
        rows = conn.execute(
            """SELECT m.id, m.user_id, m.role, m.content, m.products_json, m.created_at,
                      u.name AS user_name, u.email AS user_email
               FROM chat_messages m
               LEFT JOIN users u ON u.id = m.user_id
               ORDER BY m.id"""
        ).fetchall()

    tickets = []
    seen: dict[tuple, int] = {}
    for i, r in enumerate(rows):
        if r["role"] != "assistant":
            continue
        raw = (r["products_json"] or "").strip()
        surfaced = []
        if raw:
            try:
                surfaced = json.loads(raw)
            except json.JSONDecodeError:
                surfaced = []
        if surfaced:
            continue  # the assistant did show products — not a failure

        # An empty products list alone is not a ticket: greetings and small talk
        # also surface nothing. Require the shop to have actually said it struck out.
        reply = _normalize(r["content"])
        if not any(marker in reply for marker in FAILURE_MARKERS):
            continue

        # The preceding user message is the ask that failed.
        ask = next(
            (rows[j]["content"] for j in range(i - 1, -1, -1) if rows[j]["role"] == "user"),
            None,
        )
        if not ask:
            continue

        retry = _search_products(ask, in_stock_only=False, limit=3)
        classification = (
            "fixable_by_search" if retry["match_count"] else "true_assortment_gap"
        )
        found_ids = tuple(m["product_id"] for m in retry["matches"])

        # Customers rephrase. "handsome dan" asked two ways is one ticket, not
        # two, so collapse repeat asks from the same customer that resolve the
        # same way and count the restatements instead.
        key = (r["user_id"], found_ids or tuple(sorted(retry["unmatched_terms"])))
        if key in seen:
            prior = tickets[seen[key]]
            prior["times_asked"] += 1
            prior["restatements"].append(ask)
            continue
        seen[key] = len(tickets)

        tickets.append(
            {
                "times_asked": 1,
                "restatements": [],
                "message_id": r["id"],
                "user_id": r["user_id"],
                "user_name": r["user_name"],
                "user_email": r["user_email"],
                "asked_at": r["created_at"],
                "customer_asked": ask,
                "shop_replied": r["content"][:200],
                "classification": classification,
                "terms_tried": retry["terms_used"],
                "unmatched_terms": retry["unmatched_terms"],
                "would_now_find": [
                    {"product_id": m["product_id"], "name": m["name"], "price": m["price"]}
                    for m in retry["matches"]
                ],
                "owner": "Inventory" if classification == "true_assortment_gap"
                else "Customer Service",
            }
        )
        if len(tickets) >= limit:
            break

    counts: dict[str, int] = {}
    for t in tickets:
        counts[t["classification"]] = counts.get(t["classification"], 0) + 1

    return {
        "open_ticket_count": len(tickets),
        "by_classification": counts,
        "tickets": tickets,
    }


# --------------------------------------------------------------------------
# Tool 4 — inventory_health
# --------------------------------------------------------------------------
@mcp.tool
def inventory_health(low_stock_threshold: int = 5, limit: int = 25) -> dict:
    """Stockout and reorder picture across the whole shop.

    Inventory's standing view: how many product-size rows are sold out, how
    many are about to be, and which products are worst affected. `limit`
    caps the detail lists, not the counts — the totals are always complete.

    A product is `fully_sold_out` when no size has stock; those are invisible
    to customers but still occupy catalogue space, so they need a reorder or
    a delist decision.
    """
    with _connect() as conn:
        total, sold_out, low = conn.execute(
            """SELECT COUNT(*),
                      SUM(CASE WHEN quantity = 0 THEN 1 ELSE 0 END),
                      SUM(CASE WHEN quantity > 0 AND quantity <= ? THEN 1 ELSE 0 END)
               FROM inventory""",
            (low_stock_threshold,),
        ).fetchone()

        fully_out = conn.execute(
            """SELECT c.product_id, c.name, c.garment_type, c.price
               FROM catalogue c
               JOIN inventory i ON i.product_id = c.product_id
               GROUP BY c.product_id
               HAVING SUM(i.quantity) = 0
               ORDER BY c.price DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        low_rows = conn.execute(
            """SELECT c.product_id, c.name, i.size, i.quantity, c.price
               FROM inventory i
               JOIN catalogue c ON c.product_id = i.product_id
               WHERE i.quantity > 0 AND i.quantity <= ?
               ORDER BY i.quantity, c.price DESC
               LIMIT ?""",
            (low_stock_threshold, limit),
        ).fetchall()

        units, by_type = conn.execute(
            "SELECT SUM(quantity), COUNT(DISTINCT product_id) FROM inventory"
        ).fetchone()

    return {
        "low_stock_threshold": low_stock_threshold,
        "product_size_rows": total,
        "sold_out_rows": sold_out,
        "sold_out_pct": round(100 * sold_out / total, 1) if total else 0.0,
        "low_stock_rows": low,
        "total_units_on_hand": units,
        "products_tracked": by_type,
        "fully_sold_out_products": [dict(r) for r in fully_out],
        "fully_sold_out_count": len(fully_out),
        "reorder_soon": [dict(r) for r in low_rows],
    }


# --------------------------------------------------------------------------
# Tool 5 — revenue_exposure
# --------------------------------------------------------------------------
@mcp.tool
def revenue_exposure(limit: int = 15) -> dict:
    """Value the shelf and the holes in it, at catalogue price.

    Accounting's view. Three numbers that are easy to confuse and are
    reported separately here:

      - `stock_at_retail`      - units on hand x price. What the shelf is worth.
      - `sold_out_exposure`    - price of every sold-out product-size row. The
                                 revenue that is unavailable until restocked.
      - `fully_sold_out_value` - price of products with no size available at all.

    All figures are **retail value, not realised revenue**. There is no sales
    or order table in this database, so nothing here is a sales forecast and
    it must not be presented as one. Treat it as sizing, not accounting truth.
    """
    with _connect() as conn:
        stock_value, units = conn.execute(
            """SELECT ROUND(SUM(i.quantity * c.price), 2), SUM(i.quantity)
               FROM inventory i JOIN catalogue c ON c.product_id = i.product_id"""
        ).fetchone()

        sold_out_value, sold_out_rows = conn.execute(
            """SELECT ROUND(SUM(c.price), 2), COUNT(*)
               FROM inventory i JOIN catalogue c ON c.product_id = i.product_id
               WHERE i.quantity = 0"""
        ).fetchone()

        top = conn.execute(
            """SELECT c.product_id, c.name, c.price,
                      SUM(i.quantity) AS units,
                      ROUND(SUM(i.quantity) * c.price, 2) AS value_at_retail
               FROM inventory i JOIN catalogue c ON c.product_id = i.product_id
               GROUP BY c.product_id
               ORDER BY value_at_retail DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        fully_out_value = conn.execute(
            """SELECT ROUND(SUM(price), 2) FROM catalogue WHERE product_id IN (
                   SELECT product_id FROM inventory GROUP BY product_id
                   HAVING SUM(quantity) = 0)"""
        ).fetchone()[0]

        lo, hi, avg = conn.execute(
            "SELECT MIN(price), MAX(price), ROUND(AVG(price), 2) FROM catalogue"
        ).fetchone()

    return {
        "basis": "catalogue retail price; no sales/order table exists in this database",
        "stock_at_retail": stock_value,
        "total_units_on_hand": units,
        "sold_out_exposure": sold_out_value,
        "sold_out_rows": sold_out_rows,
        "fully_sold_out_value": fully_out_value or 0.0,
        "price_min": lo,
        "price_max": hi,
        "price_avg": avg,
        "top_value_products": [dict(r) for r in top],
    }


# --------------------------------------------------------------------------
# Tool 6 — check_asset_integrity
# --------------------------------------------------------------------------
@mcp.tool
def check_asset_integrity(limit: int = 25) -> dict:
    """Verify the unenforced links in the database actually resolve.

    Facilities' view. Two links in this schema are plain strings, not foreign
    keys, so SQLite will never complain when they rot:

      - `catalogue.image_file_path` -> a file under data/. A broken path means
        a blank tile on the storefront.
      - `chat_messages.products_json` -> `catalogue.product_id`. A stale id
        means the shop cited a product that no longer exists.

    Also reports orphaned image files on disk that no product references, and
    products with no inventory rows at all. `healthy` is true only when every
    checked link resolves.
    """
    products_dir = ROOT / "data" / "products"
    on_disk = {p.name for p in products_dir.glob("*")} if products_dir.exists() else set()

    with _connect() as conn:
        rows = conn.execute(
            "SELECT product_id, name, image_file_path FROM catalogue"
        ).fetchall()
        known_ids = {r["product_id"] for r in rows}

        missing_images = []
        referenced = set()
        for r in rows:
            fname = Path(r["image_file_path"]).name
            referenced.add(fname)
            if not (ROOT / "data" / r["image_file_path"]).exists():
                missing_images.append(
                    {
                        "product_id": r["product_id"],
                        "name": r["name"],
                        "image_file_path": r["image_file_path"],
                    }
                )

        stale_refs = []
        for m in conn.execute(
            "SELECT id, products_json FROM chat_messages WHERE products_json IS NOT NULL"
        ):
            raw = (m["products_json"] or "").strip()
            if not raw:
                continue
            try:
                items = json.loads(raw)
            except json.JSONDecodeError:
                stale_refs.append({"message_id": m["id"], "problem": "unparseable products_json"})
                continue
            for item in items or []:
                pid = item.get("product_id") if isinstance(item, dict) else None
                if pid and pid not in known_ids:
                    stale_refs.append({"message_id": m["id"], "missing_product_id": pid})

        no_inventory = [
            dict(r)
            for r in conn.execute(
                """SELECT product_id, name FROM catalogue WHERE product_id NOT IN
                   (SELECT DISTINCT product_id FROM inventory) LIMIT ?""",
                (limit,),
            )
        ]

    orphan_images = sorted(on_disk - referenced)

    return {
        "healthy": not (missing_images or stale_refs or no_inventory),
        "products_checked": len(rows),
        "missing_image_count": len(missing_images),
        "missing_images": missing_images[:limit],
        "stale_product_reference_count": len(stale_refs),
        "stale_product_references": stale_refs[:limit],
        "products_without_inventory": no_inventory,
        "orphan_image_files": orphan_images[:limit],
        "orphan_image_count": len(orphan_images),
    }


# --------------------------------------------------------------------------
# Tool 7 — record_ticket_resolution (append-only write)
# --------------------------------------------------------------------------
@mcp.tool
def record_ticket_resolution(
    ticket_ref: str,
    decision: str,
    rationale: str,
    decided_by: str,
    owner: str,
    product_ids: list[str] | None = None,
) -> dict:
    """Write a ticket decision into the shop's permanent record.

    The only tool in this server that writes. It is strictly **append-only**:
    rows are inserted into `ticket_resolutions` and never updated or deleted,
    so a wrong decision is corrected by recording a new one, not by erasing
    the old. That keeps the business record auditable.

    `decided_by` must name the agent making the call and `rationale` must
    explain why — a resolution with no reasoning is not accepted. Returns the
    stored row including its `resolution_id` and timestamp.
    """
    for field_name, value in (
        ("ticket_ref", ticket_ref),
        ("decision", decision),
        ("rationale", rationale),
        ("decided_by", decided_by),
        ("owner", owner),
    ):
        if not value or not str(value).strip():
            return {"written": False, "error": f"{field_name} is required and cannot be empty"}

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ticket_resolutions (
                   resolution_id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ticket_ref TEXT NOT NULL,
                   decision TEXT NOT NULL,
                   rationale TEXT NOT NULL,
                   decided_by TEXT NOT NULL,
                   owner TEXT NOT NULL,
                   product_ids TEXT NOT NULL DEFAULT '[]',
                   recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        cur = conn.execute(
            """INSERT INTO ticket_resolutions
                   (ticket_ref, decision, rationale, decided_by, owner, product_ids)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                ticket_ref.strip(),
                decision.strip(),
                rationale.strip(),
                decided_by.strip(),
                owner.strip(),
                json.dumps(product_ids or []),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ticket_resolutions WHERE resolution_id = ?", (cur.lastrowid,)
        ).fetchone()
        total = conn.execute("SELECT COUNT(*) FROM ticket_resolutions").fetchone()[0]
    finally:
        conn.close()

    return {"written": True, "resolution": dict(row), "total_resolutions_on_record": total}


def main() -> None:
    ap = argparse.ArgumentParser(description="Campus Customs shop MCP server")
    ap.add_argument("--http", action="store_true", help="serve over HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8002)
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
