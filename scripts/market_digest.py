"""Read-only Polymarket sampling and like-for-like rankings; no prediction engine."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
import json
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = "https://gamma-api.polymarket.com/markets/keyset"
SCOPE = "gamma-keyset:closed=false;order=id;ascending=true;active-unarchived-local:v1"
MAX_RESPONSE = 16 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp(s):
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("observation timestamps must include an offset")
    return t.astimezone(timezone.utc)


def number(v, maximum=None):
    try:
        n = Decimal(str(v))
        if n.is_finite() and 0 <= n and (maximum is None or n <= maximum):
            return n
    except (InvalidOperation, ValueError):
        pass
    return None


def numeric_field(row, *keys):
    for key in keys:
        n = number(row.get(key))
        if n is not None:
            return str(n)
    return None


def array(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def market_id(row):
    v = str(row.get("id", "")) if isinstance(row, dict) else ""
    if not v or not v.isascii() or not v.isdigit() or len(v) > 32:
        raise ValueError("missing or invalid market ID")
    return str(int(v))


def normalize(row, observed_at):
    labels = [x.strip().casefold() if isinstance(x, str) else None
              for x in array(row.get("outcomes"))]
    prices = array(row.get("outcomePrices"))
    tokens = array(row.get("clobTokenIds"))
    binary = len(labels) == 2 and set(labels) == {"yes", "no"}
    i = labels.index("yes") if binary else 0
    yes = number(prices[i], Decimal(1)) if binary and len(prices) == 2 else None
    token = str(tokens[i]) if binary and len(tokens) == 2 else None
    if not token or not token.isascii() or not token.isdigit():
        token = None
    events = row.get("events")
    event = events[0] if isinstance(events, list) and events and isinstance(events[0], dict) else {}
    return {
        "market_id": market_id(row), "condition_id": row.get("conditionId"),
        "event_id": event.get("id"), "event_slug": event.get("slug"),
        "market_slug": row.get("slug"), "question": row.get("question"),
        "category_hint": row.get("category") or event.get("category"),
        "sports_type_hint": row.get("sportsMarketType"),
        "accepting_orders": row.get("acceptingOrders") if isinstance(row.get("acceptingOrders"), bool) else None,
        "resolution_source": row.get("resolutionSource"), "end_at": row.get("endDate"),
        "observed_at": observed_at, "source_updated_at": row.get("updatedAt"),
        "yes": None if yes is None else str(yes), "yes_token": token,
        "volume_24h": numeric_field(row, "volume24hr"),
        "liquidity": numeric_field(row, "liquidityNum", "liquidity"),
        "raw_change_24h_unverified": row.get("oneDayPriceChange"),
    }


def collect(fetch, max_pages, started_at):
    rows, requested = {}, set()
    pages = raw = repeats = excluded = 0
    cursor, last_at, previous_id = None, None, None
    complete = False
    stop = "page_budget"
    try:
        for _ in range(max_pages):
            if cursor in requested:
                stop = "cursor_loop"
                break
            requested.add(cursor)
            observed_at, payload = fetch(cursor)
            timestamp(observed_at)
            if not isinstance(payload, dict) or not isinstance(payload.get("markets"), list):
                raise ValueError("response does not contain a markets array")
            markets = payload["markets"]
            next_cursor = payload.get("next_cursor")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise ValueError("invalid next_cursor")
            checked = [(market_id(row), row) for row in markets]
            # Overlap is allowed at a boundary, but changed ordering means coverage may have holes.
            ids = [int(i) for i, _ in checked]
            if ids != sorted(ids) or (ids and previous_id is not None and ids[0] < previous_id):
                stop = "inconsistent_id_order"
                break
            if ids:
                previous_id = ids[-1]
            pages += 1
            last_at = observed_at
            for k, row in checked:
                raw += 1
                if row.get("active") is not True or row.get("closed") is not False or row.get("archived") is True:
                    excluded += 1
                    rows.pop(k, None)
                    continue
                repeats += k in rows
                rows[k] = normalize(row, observed_at)
            if not next_cursor:
                complete, stop = True, "cursor_exhausted"
                break
            if not markets:
                stop = "empty_continuation"
                break
            if next_cursor in requested:
                stop = "cursor_loop"
                break
            cursor = next_cursor
    except HTTPError as e:
        stop = "http_" + str(e.code)
    except (URLError, HTTPException, TimeoutError):
        stop = "network_error"
    except (ValueError, TypeError, KeyError, AttributeError):
        stop = "invalid_page"
    return {
        "schema": 1, "scope": SCOPE, "started_at": started_at,
        "last_page_observed_at": last_at, "pages": pages, "raw_rows": raw,
        "duplicate_eligible_observations": repeats, "excluded_rows": excluded,
        "terminal_cursor_reached": complete, "stop": stop,
        "markets": [rows[k] for k in sorted(rows, key=int)],
    }


def fixture_source(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = iter(data["pages"])

    def fetch(cursor):
        page = next(pages, None)
        if page is None or page["after_cursor"] != cursor:
            raise ValueError("fixture does not match requested cursor")
        return page["observed_at"], page["response"]
    return data["started_at"], fetch


def live_source(limit):
    opener = build_opener(NoRedirect())

    def fetch(cursor):
        query = {"limit": limit, "closed": "false", "order": "id", "ascending": "true"}
        if cursor:
            query["after_cursor"] = cursor
        req = Request(ENDPOINT + "?" + urlencode(query), headers={"Accept": "application/json", "User-Agent": "market-observation-skill/1.0"})
        for attempt in range(3):
            try:
                if cursor is not None and attempt == 0:
                    time.sleep(0.15)
                with opener.open(req, timeout=15) as response:
                    body = response.read(MAX_RESPONSE + 1)
                if len(body) > MAX_RESPONSE:
                    raise ValueError("response exceeds size limit")
                return now(), json.loads(body)
            except HTTPError as e:
                if e.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                retry_after = e.headers.get("Retry-After", "")
                # Honor a longer or nonnumeric Retry-After by stopping instead of retrying early.
                if retry_after and (not retry_after.isdecimal() or len(retry_after) > 2 or int(retry_after) > 10):
                    raise
                time.sleep(max(2 ** attempt, int(retry_after or "0")))
            except (URLError, HTTPException, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
    return now(), fetch


def rank(snapshot, prior=None):
    if prior is not None and (prior.get("schema") != 1 or prior.get("scope") != snapshot["scope"]):
        raise ValueError("prior snapshot has incompatible schema or scope")
    old = {r["market_id"]: r for r in prior["markets"]} if prior is not None else {}
    rows = [dict(r) for r in snapshot["markets"]]
    for r in rows:
        p = old.get(r["market_id"])
        yes = number(r.get("yes"), Decimal(1))
        q = number(p.get("yes"), Decimal(1)) if p else None
        r.update(change_pp=None, prior_observed_at=None, comparison_interval_seconds=None,
                 first_seen_in_sample=(p is None) if prior is not None else None)
        if (p and yes is not None and q is not None and r.get("yes_token") and
                r["yes_token"] == p.get("yes_token") and r.get("condition_id") and
                r["condition_id"] == p.get("condition_id")):
            dt = (timestamp(r["observed_at"]) - timestamp(p["observed_at"])).total_seconds()
            if dt > 0:
                r.update(change_pp=str((yes - q) * 100), prior_observed_at=p["observed_at"],
                         comparison_interval_seconds=dt)
    def ordered(field, absolute=False):
        def key(r):
            v = Decimal(r[field])
            return (-(abs(v) if absolute else v), int(r["market_id"]))
        return [r["market_id"] for r in sorted((r for r in rows if r[field] is not None), key=key)]
    return {
        "scope": snapshot["scope"], "rows": rows, "eligible_markets": len(rows),
        "comparable_changes": sum(r["change_pp"] is not None for r in rows),
        "prior_terminal_cursor_reached": prior.get("terminal_cursor_reached") if prior is not None else None,
        "absolute_change_ids": ordered("change_pp", absolute=True),
        "volume_24h_ids": ordered("volume_24h"), "liquidity_ids": ordered("liquidity"),
    }


def event_split(buckets, absent, *, disjoint_exhaustive=False, same_settlement=False):
    """Aggregate reviewed outcome buckets only. Never infer disjointness or shared rules."""
    if disjoint_exhaustive is not True or same_settlement is not True:
        raise ValueError("verify a disjoint exhaustive partition with identical settlement first")
    if not isinstance(buckets, dict) or absent not in buckets or len(buckets) < 2:
        raise ValueError("a complete map of distinct buckets and explicit absence is required")
    rates = {label: number(value, Decimal(1)) for label, value in buckets.items()}
    if any(v is None for v in rates.values()):
        raise ValueError("missing or invalid probability")
    total = sum(rates.values())
    other = {label: v for label, v in rates.items() if label != absent}
    event = sum(other.values())
    highest = max(other.values())
    # Separately quoted outcomes need not sum to one; report the raw total.
    usable = abs(total - Decimal(1)) <= Decimal("0.02") and event <= 1
    return {
        "raw_total": total, "usable_as_distribution": usable,
        "event_unconditional": event if usable else None,
        "largest_bucket_labels": sorted(label for label in other if other[label] == highest),
        "largest_bucket_unconditional": highest if usable else None,
        "largest_bucket_conditional_on_event": highest / event if usable and event > 0 else None,
    }


def save(path, payload):
    # Publish completed JSON only; don't leave a half-written file in place on error.
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as f:
            name = Path(f.name)
            json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        name.replace(path)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path)
    source.add_argument("--live", action="store_true")
    parser.add_argument("--prior", type=Path, help="Prior normalized snapshot.json, or an offline fixture")
    parser.add_argument("--out", type=Path, required=True, help="Output directory; existing outputs are not replaced")
    parser.add_argument("--page-size", type=int, default=100, choices=range(1, 101), metavar="1..100")
    parser.add_argument("--max-pages", type=int, default=20, choices=range(1, 10001), metavar="1..10000")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    snapshot_path, rank_path = (args.out / f for f in ("snapshot.json", "ranked.json"))
    if snapshot_path.exists() or rank_path.exists():
        parser.error("output exists; choose a fresh output directory")
    prior = None
    if args.prior is not None:
        prior = json.loads(args.prior.read_text(encoding="utf-8"))
        if "pages" in prior and "schema" not in prior:
            started, getter = fixture_source(args.prior)
            prior = collect(getter, 10000, started)
    started, getter = live_source(args.page_size) if args.live else fixture_source(args.fixture)
    snapshot = collect(getter, args.max_pages, started)
    ranked = rank(snapshot, prior)
    save(snapshot_path, snapshot)
    save(rank_path, ranked)
    print(json.dumps({k: snapshot[k] for k in ("pages", "raw_rows", "terminal_cursor_reached", "stop")}))
    return 0 if snapshot["terminal_cursor_reached"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
