import json
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.routes.service import weighted_lotto


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "weighted_lotto.db"
    monkeypatch.setattr(weighted_lotto, "DB_PATH", test_db)
    weighted_lotto._initialize_tables()

    app = create_app()
    app.config.update(TESTING=True, LOTTO_TTL_HOURS=24)

    with app.test_client() as test_client:
        yield test_client


def _make_mock_response(payload=None, status=200, text=None, raise_exc=None):
    """Build a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status
    if raise_exc:
        mock.raise_for_status.side_effect = raise_exc
    else:
        mock.raise_for_status.return_value = None
    if payload is not None:
        mock.json.return_value = payload
        mock.text = json.dumps(payload)
    elif text is not None:
        mock.json.side_effect = ValueError("not json")
        mock.text = text
    return mock


# ---------------------------------------------------------------------------
# /lotteries — GET
# ---------------------------------------------------------------------------


def test_list_lotteries_returns_five_builtins(client):
    response = client.get("/service/weighted_lotto/lotteries")
    assert response.status_code == 200
    lotteries = response.get_json()["lotteries"]
    names = {lotto["name"] for lotto in lotteries}
    assert names == {"powerball", "mega_millions", "euromillions", "pick3", "pick4"}


# ---------------------------------------------------------------------------
# /register — POST
# ---------------------------------------------------------------------------


def test_register_custom_lottery_success(client):
    payload = {
        "name": "my_custom",
        "main_pool_size": 40,
        "main_pick_count": 6,
        "bonus_pool_size": 10,
        "bonus_pick_count": 1,
        "fetch_url": "https://example.com/results",
        "fetch_type": "api",
    }
    response = client.post("/service/weighted_lotto/register", json=payload)
    assert response.status_code == 201
    assert response.get_json()["message"] == "lottery registered"


def test_register_missing_required_field_returns_400(client):
    payload = {"name": "bad_lottery", "main_pool_size": 40}
    response = client.post("/service/weighted_lotto/register", json=payload)
    assert response.status_code == 400
    assert "Missing required fields" in response.get_json()["error"]


def test_register_duplicate_name_returns_409(client):
    payload = {
        "name": "powerball",
        "main_pool_size": 69,
        "main_pick_count": 5,
        "fetch_url": "",
        "fetch_type": "api",
    }
    response = client.post("/service/weighted_lotto/register", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.get_json()["error"]


def test_register_invalid_fetch_type_returns_400(client):
    payload = {
        "name": "bad_type",
        "main_pool_size": 40,
        "main_pick_count": 6,
        "fetch_url": "https://example.com",
        "fetch_type": "ftp",
    }
    response = client.post("/service/weighted_lotto/register", json=payload)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# /fetch/<name> — POST
# ---------------------------------------------------------------------------


def test_fetch_lottery_unknown_name_returns_404(client):
    response = client.post("/service/weighted_lotto/fetch/unknown_lottery")
    assert response.status_code == 404


def test_fetch_lottery_no_url_returns_422(client):
    # powerball built-in has empty fetch_url
    response = client.post("/service/weighted_lotto/fetch/powerball")
    assert response.status_code == 422


def test_fetch_lottery_api_success(client, monkeypatch, tmp_path):
    # Register a custom lottery with a fetch_url
    client.post(
        "/service/weighted_lotto/register",
        json={
            "name": "test_lotto",
            "main_pool_size": 10,
            "main_pick_count": 3,
            "fetch_url": "https://example.com/api/draws",
            "fetch_type": "api",
        },
    )

    api_payload = {
        "data": [
            {"draw_date": "2024-01-01", "numbers": [1, 2, 3], "bonus_numbers": []},
            {"draw_date": "2024-01-02", "numbers": [4, 5, 6], "bonus_numbers": []},
        ]
    }
    mock_resp = _make_mock_response(payload=api_payload)

    with patch("app.routes.service.weighted_lotto.requests.get", return_value=mock_resp):
        response = client.post("/service/weighted_lotto/fetch/test_lotto")

    assert response.status_code == 200
    data = response.get_json()
    assert data["new_records"] == 2


def test_fetch_lottery_scrape_fallback(client, monkeypatch):
    client.post(
        "/service/weighted_lotto/register",
        json={
            "name": "scrape_lotto",
            "main_pool_size": 50,
            "main_pick_count": 5,
            "fetch_url": "https://example.com/draws",
            "fetch_type": "scrape",
        },
    )

    html_body = """
    <html><body><table>
      <tr><td>2024-03-01</td><td>10</td><td>20</td><td>30</td><td>40</td><td>50</td></tr>
      <tr><td>2024-03-02</td><td>5</td><td>15</td><td>25</td><td>35</td><td>45</td></tr>
    </table></body></html>
    """
    mock_resp = _make_mock_response(text=html_body)

    with patch("app.routes.service.weighted_lotto.requests.get", return_value=mock_resp):
        response = client.post("/service/weighted_lotto/fetch/scrape_lotto")

    assert response.status_code == 200
    assert response.get_json()["new_records"] == 2


# ---------------------------------------------------------------------------
# /generate/<name> — GET
# ---------------------------------------------------------------------------


def test_generate_fallback_uniform_no_history(client):
    response = client.get("/service/weighted_lotto/generate/powerball")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["numbers"]) == 5
    assert len(data["bonus_numbers"]) == 1
    assert data["note"] is not None  # uniform fallback note present


def test_generate_unknown_lottery_returns_404(client):
    response = client.get("/service/weighted_lotto/generate/nonexistent")
    assert response.status_code == 404


def test_generate_invalid_strategy_returns_400(client):
    response = client.get("/service/weighted_lotto/generate/powerball?strategy=lucky")
    assert response.status_code == 400


def _seed_draw_history(lottery_name, count=15):
    """Insert synthetic draw history so weighting logic is exercised."""
    connection = weighted_lotto._get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "SELECT id, main_pool_size, main_pick_count FROM lottery_configs WHERE name = ?",
        (lottery_name,),
    )
    cfg = cursor.fetchone()
    pool = list(range(1, cfg["main_pool_size"] + 1))
    import random
    from datetime import date, timedelta

    now = date(2024, 1, 1)
    for i in range(count):
        draw_date = (now + timedelta(days=i)).isoformat()
        numbers = json.dumps(random.sample(pool, cfg["main_pick_count"]))
        cursor.execute(
            "INSERT OR IGNORE INTO draw_results (lottery_id, draw_date, numbers, bonus_numbers, created_at) VALUES (?,?,?,?,?)",
            (cfg["id"], draw_date, numbers, "[]", draw_date),
        )
    connection.commit()
    connection.close()


@pytest.mark.parametrize("strategy", ["hot", "cold", "hybrid"])
def test_generate_all_strategies_with_history(client, strategy):
    _seed_draw_history("euromillions", count=20)
    response = client.get(f"/service/weighted_lotto/generate/euromillions?strategy={strategy}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["strategy"] == strategy
    assert len(data["numbers"]) == 5
    assert data["draw_count_used"] == 20
    assert data["note"] is None  # history is sufficient
    # All numbers in valid pool range
    assert all(1 <= n <= 50 for n in data["numbers"])


# ---------------------------------------------------------------------------
# /stats/<name> — GET
# ---------------------------------------------------------------------------


def test_stats_unknown_lottery_returns_404(client):
    response = client.get("/service/weighted_lotto/stats/nonexistent")
    assert response.status_code == 404


def test_stats_no_history_returns_zero_count(client):
    response = client.get("/service/weighted_lotto/stats/powerball")
    assert response.status_code == 200
    assert response.get_json()["draw_count"] == 0


def test_stats_with_history_returns_hot_cold(client):
    _seed_draw_history("powerball", count=15)
    response = client.get("/service/weighted_lotto/stats/powerball?top=5")
    assert response.status_code == 200
    data = response.get_json()
    assert data["draw_count"] == 15
    assert len(data["main_numbers"]["hot"]) <= 5
    assert len(data["main_numbers"]["cold"]) <= 5
    # Hot numbers have frequency attached
    for item in data["main_numbers"]["hot"]:
        assert "number" in item and "frequency" in item
