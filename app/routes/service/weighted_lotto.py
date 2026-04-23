import json
import random
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("weighted_lotto", __name__, url_prefix="/service/weighted_lotto")

DB_PATH = Path(__file__).resolve().parent / "weighted_lotto.db"

# ---------------------------------------------------------------------------
# Built-in lottery seed configurations
# ---------------------------------------------------------------------------
_BUILTIN_LOTTERIES = [
    {
        "name": "powerball",
        "main_pool_size": 69,
        "main_pick_count": 5,
        "bonus_pool_size": 26,
        "bonus_pick_count": 1,
        "fetch_url": "",
        "fetch_type": "api",
    },
    {
        "name": "mega_millions",
        "main_pool_size": 70,
        "main_pick_count": 5,
        "bonus_pool_size": 25,
        "bonus_pick_count": 1,
        "fetch_url": "",
        "fetch_type": "api",
    },
    {
        "name": "euromillions",
        "main_pool_size": 50,
        "main_pick_count": 5,
        "bonus_pool_size": 12,
        "bonus_pick_count": 2,
        "fetch_url": "",
        "fetch_type": "api",
    },
    {
        "name": "pick3",
        "main_pool_size": 10,
        "main_pick_count": 3,
        "bonus_pool_size": None,
        "bonus_pick_count": None,
        "fetch_url": "",
        "fetch_type": "api",
    },
    {
        "name": "pick4",
        "main_pool_size": 10,
        "main_pick_count": 4,
        "bonus_pool_size": None,
        "bonus_pick_count": None,
        "fetch_url": "",
        "fetch_type": "api",
    },
]

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize_tables():
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS lottery_configs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL UNIQUE,
            main_pool_size  INTEGER NOT NULL,
            main_pick_count INTEGER NOT NULL,
            bonus_pool_size  INTEGER,
            bonus_pick_count INTEGER,
            fetch_url       TEXT    NOT NULL DEFAULT '',
            fetch_type      TEXT    NOT NULL DEFAULT 'api',
            last_fetched    TEXT,
            created_at      TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS draw_results (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_id     INTEGER NOT NULL REFERENCES lottery_configs(id),
            draw_date      TEXT    NOT NULL,
            numbers        TEXT    NOT NULL,
            bonus_numbers  TEXT    NOT NULL DEFAULT '[]',
            created_at     TEXT    NOT NULL,
            UNIQUE(lottery_id, draw_date)
        );
        """
    )

    now = datetime.now(timezone.utc).isoformat()
    for cfg in _BUILTIN_LOTTERIES:
        cursor.execute(
            """
            INSERT OR IGNORE INTO lottery_configs
                (name, main_pool_size, main_pick_count, bonus_pool_size,
                 bonus_pick_count, fetch_url, fetch_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cfg["name"],
                cfg["main_pool_size"],
                cfg["main_pick_count"],
                cfg["bonus_pool_size"],
                cfg["bonus_pick_count"],
                cfg["fetch_url"],
                cfg["fetch_type"],
                now,
            ),
        )

    connection.commit()
    connection.close()


_initialize_tables()


# ---------------------------------------------------------------------------
# Fetch engine
# ---------------------------------------------------------------------------


def _parse_api_response(data, lottery_id):
    """
    Try to interpret a JSON response as a list of draw records.
    Accepts two common shapes:
      - list of {draw_date, numbers, bonus_numbers?}
      - {data: [...]} or {results: [...]} wrapper
    Returns list of normalised dicts or None on failure.
    """
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = data.get("data") or data.get("results") or data.get("draws") or []
    else:
        return None

    parsed = []
    for item in records:
        if not isinstance(item, dict):
            continue
        draw_date = item.get("draw_date") or item.get("date") or item.get("drawDate")
        numbers = item.get("numbers") or item.get("winning_numbers") or item.get("mainNumbers")
        bonus = item.get("bonus_numbers") or item.get("bonus") or item.get("bonusNumbers") or []
        if draw_date and numbers and isinstance(numbers, list):
            parsed.append(
                {
                    "lottery_id": lottery_id,
                    "draw_date": str(draw_date),
                    "numbers": json.dumps([int(n) for n in numbers]),
                    "bonus_numbers": json.dumps([int(b) for b in bonus]),
                }
            )
    return parsed if parsed else None


def _parse_html_response(html, lottery_id):
    """
    Generic HTML scraper: looks for any <table> containing numeric cells
    and treats the first date-like column as draw_date and remaining numeric
    columns as drawn numbers.
    Returns list of normalised dicts or empty list.
    """
    soup = BeautifulSoup(html, "html.parser")
    parsed = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            # Heuristic: first cell looks like a date if it contains "-" or "/"
            draw_date = cells[0] if ("-" in cells[0] or "/" in cells[0]) else None
            if draw_date is None:
                continue
            numbers = []
            for cell in cells[1:]:
                try:
                    numbers.append(int(cell))
                except ValueError:
                    pass
            if numbers:
                parsed.append(
                    {
                        "lottery_id": lottery_id,
                        "draw_date": draw_date,
                        "numbers": json.dumps(numbers),
                        "bonus_numbers": json.dumps([]),
                    }
                )

    return parsed


def _insert_draw_records(records):
    """Insert records, skip duplicates. Returns count of newly inserted rows."""
    if not records:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    connection = _get_connection()
    cursor = connection.cursor()
    for rec in records:
        cursor.execute(
            """
            INSERT OR IGNORE INTO draw_results
                (lottery_id, draw_date, numbers, bonus_numbers, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rec["lottery_id"], rec["draw_date"], rec["numbers"], rec["bonus_numbers"], now),
        )
        inserted += cursor.rowcount
    connection.commit()
    connection.close()
    return inserted


def _fetch_from_source(config):
    """
    Attempt to fetch draw history for *config* (a dict-like row from lottery_configs).
    Tries JSON API first; falls back to HTML scraping.
    Updates last_fetched timestamp regardless of new-record count.
    Returns count of newly inserted draw records.
    """
    fetch_url = config["fetch_url"]
    lottery_id = config["id"]

    if not fetch_url:
        return 0

    records = None

    # --- API attempt ---
    try:
        response = requests.get(fetch_url, timeout=10)
        response.raise_for_status()
        try:
            data = response.json()
            records = _parse_api_response(data, lottery_id)
        except ValueError:
            pass  # not JSON — fall through to scrape
    except requests.RequestException:
        pass

    # --- Scraping fallback ---
    if records is None:
        try:
            response = requests.get(fetch_url, timeout=10)
            records = _parse_html_response(response.text, lottery_id)
        except requests.RequestException:
            records = []

    inserted = _insert_draw_records(records)

    # Update last_fetched
    now = datetime.now(timezone.utc).isoformat()
    connection = _get_connection()
    connection.execute(
        "UPDATE lottery_configs SET last_fetched = ? WHERE id = ?",
        (now, lottery_id),
    )
    connection.commit()
    connection.close()

    return inserted


def _maybe_refresh(config, ttl_hours=24):
    """
    If last_fetched is absent or older than ttl_hours, trigger a background fetch.
    """
    last = config["last_fetched"]
    if last:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
        if age.total_seconds() < ttl_hours * 3600:
            return

    thread = threading.Thread(
        target=_fetch_from_source, args=(dict(config),), daemon=True
    )
    thread.start()


# ---------------------------------------------------------------------------
# Weighting algorithm
# ---------------------------------------------------------------------------


def _weighted_sample_no_replacement(population, weights, k):
    """
    Draw k unique items from population using the given weights (without replacement).
    """
    remaining_pop = list(population)
    remaining_weights = list(weights)
    result = []
    for _ in range(k):
        if not remaining_pop:
            break
        chosen = random.choices(remaining_pop, weights=remaining_weights, k=1)[0]
        idx = remaining_pop.index(chosen)
        result.append(chosen)
        remaining_pop.pop(idx)
        remaining_weights.pop(idx)
    return result


def _compute_weights(lottery_id, pool_size, pick_count, strategy, is_bonus=False):
    """
    Returns a list of *pick_count* numbers drawn from [1..pool_size] (or [0..pool_size-1]
    for pick3/pick4 which use 0-based pools).
    Falls back to uniform random.sample when fewer than 10 draws exist.
    """
    connection = _get_connection()
    cursor = connection.cursor()

    field = "bonus_numbers" if is_bonus else "numbers"
    cursor.execute(
        f"SELECT {field} FROM draw_results WHERE lottery_id = ?",  # noqa: S608
        (lottery_id,),
    )
    rows = cursor.fetchall()
    connection.close()

    # Determine pool: pick3/pick4 use 0–9; all others use 1–pool_size
    pool = list(range(pool_size)) if pool_size == 10 else list(range(1, pool_size + 1))

    if len(rows) < 10:
        return random.sample(pool, min(pick_count, len(pool)))

    freq = {n: 0 for n in pool}
    for row in rows:
        for n in json.loads(row[0]):
            if n in freq:
                freq[n] += 1

    total = sum(freq.values()) or 1

    if strategy == "hot":
        # Add epsilon so numbers never drawn still have a non-zero selection chance
        epsilon = 1e-6
        weights = [freq[n] / total + epsilon for n in pool]
    elif strategy == "cold":
        raw = [1.0 / (freq[n] + 1) for n in pool]
        total_raw = sum(raw)
        weights = [w / total_raw for w in raw]
    else:  # hybrid — 50/50 blend
        hot_w = [freq[n] / total for n in pool]
        cold_raw = [1.0 / (freq[n] + 1) for n in pool]
        cold_total = sum(cold_raw)
        cold_w = [w / cold_total for w in cold_raw]
        weights = [(h + c) / 2 for h, c in zip(hot_w, cold_w)]

    return _weighted_sample_no_replacement(pool, weights, min(pick_count, len(pool)))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.route("/lotteries", methods=["GET"])
def list_lotteries():
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM lottery_configs ORDER BY id")
    rows = cursor.fetchall()
    connection.close()
    return jsonify({"lotteries": [dict(r) for r in rows]}), 200


@bp.route("/register", methods=["POST"])
def register_lottery():
    payload = request.get_json(silent=True) or {}

    required = ["name", "main_pool_size", "main_pick_count", "fetch_url", "fetch_type"]
    missing = [f for f in required if payload.get(f) is None]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    if payload["fetch_type"] not in ("api", "scrape"):
        return jsonify({"error": "fetch_type must be 'api' or 'scrape'"}), 400

    now = datetime.now(timezone.utc).isoformat()
    try:
        connection = _get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO lottery_configs
                (name, main_pool_size, main_pick_count, bonus_pool_size,
                 bonus_pick_count, fetch_url, fetch_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["name"].lower().strip(),
                int(payload["main_pool_size"]),
                int(payload["main_pick_count"]),
                int(payload["bonus_pool_size"]) if payload.get("bonus_pool_size") is not None else None,
                int(payload["bonus_pick_count"]) if payload.get("bonus_pick_count") is not None else None,
                payload["fetch_url"],
                payload["fetch_type"],
                now,
            ),
        )
        connection.commit()
        new_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "lottery name already exists"}), 409
    finally:
        connection.close()

    return jsonify({"message": "lottery registered", "id": new_id}), 201


@bp.route("/fetch/<string:name>", methods=["POST"])
def fetch_lottery(name):
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM lottery_configs WHERE name = ?", (name.lower(),))
    row = cursor.fetchone()
    connection.close()

    if row is None:
        return jsonify({"error": f"lottery '{name}' not found"}), 404

    if not row["fetch_url"]:
        return jsonify({"error": "no fetch_url configured for this lottery"}), 422

    inserted = _fetch_from_source(dict(row))
    return jsonify({"message": "fetch complete", "new_records": inserted}), 200


@bp.route("/generate/<string:name>", methods=["GET"])
def generate_numbers(name):
    strategy = request.args.get("strategy", "hybrid").lower()
    if strategy not in ("hot", "cold", "hybrid"):
        return jsonify({"error": "strategy must be 'hot', 'cold', or 'hybrid'"}), 400

    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM lottery_configs WHERE name = ?", (name.lower(),))
    config = cursor.fetchone()
    connection.close()

    if config is None:
        return jsonify({"error": f"lottery '{name}' not found"}), 404

    ttl_hours = current_app.config.get("LOTTO_TTL_HOURS", 24)
    _maybe_refresh(config, ttl_hours=ttl_hours)

    # Count available draws for transparency
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM draw_results WHERE lottery_id = ?", (config["id"],)
    )
    draw_count = cursor.fetchone()["cnt"]
    connection.close()

    numbers = sorted(
        _compute_weights(
            config["id"], config["main_pool_size"], config["main_pick_count"], strategy
        )
    )

    bonus_numbers = []
    if config["bonus_pool_size"] and config["bonus_pick_count"]:
        bonus_numbers = sorted(
            _compute_weights(
                config["id"],
                config["bonus_pool_size"],
                config["bonus_pick_count"],
                strategy,
                is_bonus=True,
            )
        )

    return jsonify(
        {
            "lottery": config["name"],
            "strategy": strategy,
            "numbers": numbers,
            "bonus_numbers": bonus_numbers,
            "draw_count_used": draw_count,
            "note": "uniform random (insufficient history)" if draw_count < 10 else None,
        }
    ), 200


@bp.route("/stats/<string:name>", methods=["GET"])
def lottery_stats(name):
    top_n = min(int(request.args.get("top", 10)), 50)

    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM lottery_configs WHERE name = ?", (name.lower(),))
    config = cursor.fetchone()
    if config is None:
        connection.close()
        return jsonify({"error": f"lottery '{name}' not found"}), 404

    cursor.execute(
        "SELECT numbers, bonus_numbers FROM draw_results WHERE lottery_id = ?",
        (config["id"],),
    )
    rows = cursor.fetchall()
    connection.close()

    if not rows:
        return jsonify({"lottery": config["name"], "draw_count": 0, "hot": [], "cold": []}), 200

    freq = {}
    for row in rows:
        for n in json.loads(row["numbers"]):
            freq[n] = freq.get(n, 0) + 1

    bonus_freq = {}
    for row in rows:
        for n in json.loads(row["bonus_numbers"]):
            bonus_freq[n] = bonus_freq.get(n, 0) + 1

    sorted_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    hot = [{"number": n, "frequency": c} for n, c in sorted_freq[:top_n]]
    cold = [{"number": n, "frequency": c} for n, c in sorted_freq[-top_n:]]

    bonus_sorted = sorted(bonus_freq.items(), key=lambda x: x[1], reverse=True)
    hot_bonus = [{"number": n, "frequency": c} for n, c in bonus_sorted[:top_n]]
    cold_bonus = [{"number": n, "frequency": c} for n, c in bonus_sorted[-top_n:]]

    return jsonify(
        {
            "lottery": config["name"],
            "draw_count": len(rows),
            "main_numbers": {"hot": hot, "cold": cold},
            "bonus_numbers": {"hot": hot_bonus, "cold": cold_bonus},
        }
    ), 200
