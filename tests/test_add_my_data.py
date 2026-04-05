import pytest

from app import create_app
from app.routes.service import add_my_data


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db_path = tmp_path / "products.db"
    monkeypatch.setattr(add_my_data, "DB_PATH", test_db_path)
    add_my_data._initialize_table()

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as test_client:
        yield test_client


def test_create_product_success(client):
    payload = {
        "vendor": "Acme",
        "product_name": "Widget",
        "url": "https://example.com/widget",
        "product_id": "W123",
    }

    response = client.post("/service/add_my_data", json=payload)

    assert response.status_code == 201
    assert response.get_json()["message"] == "product saved"


def test_create_product_missing_required_field_returns_400(client):
    payload = {
        "vendor": "Acme",
        "product_name": "Widget",
        "url": "https://example.com/widget",
    }

    response = client.post("/service/add_my_data", json=payload)

    assert response.status_code == 400
    assert "Missing required fields" in response.get_json()["error"]


def test_create_product_duplicate_product_id_returns_409(client):
    payload = {
        "vendor": "Acme",
        "product_name": "Widget",
        "url": "https://example.com/widget",
        "product_id": "W123",
    }

    first = client.post("/service/add_my_data", json=payload)
    second = client.post("/service/add_my_data", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.get_json()["error"] == "product_id already exists"


def test_get_products_returns_all(client):
    first_payload = {
        "vendor": "Acme",
        "product_name": "Widget",
        "url": "https://example.com/widget",
        "product_id": "W123",
    }
    second_payload = {
        "vendor": "Globex",
        "product_name": "Gadget",
        "url": "https://example.com/gadget",
        "product_id": "G456",
    }

    client.post("/service/add_my_data", json=first_payload)
    client.post("/service/add_my_data", json=second_payload)

    response = client.get("/service/add_my_data")

    assert response.status_code == 200
    products = response.get_json()["products"]
    assert len(products) == 2
    product_ids = {product["product_id"] for product in products}
    assert product_ids == {"W123", "G456"}


def test_get_products_with_product_id_filter_returns_match(client):
    first_payload = {
        "vendor": "Acme",
        "product_name": "Widget",
        "url": "https://example.com/widget",
        "product_id": "W123",
    }
    second_payload = {
        "vendor": "Globex",
        "product_name": "Gadget",
        "url": "https://example.com/gadget",
        "product_id": "G456",
    }

    client.post("/service/add_my_data", json=first_payload)
    client.post("/service/add_my_data", json=second_payload)

    response = client.get("/service/add_my_data?product_id=W123")

    assert response.status_code == 200
    products = response.get_json()["products"]
    assert len(products) == 1
    assert products[0]["product_id"] == "W123"


def test_delete_product_success(client):
    payload = {
        "vendor": "Acme",
        "product_name": "Widget",
        "url": "https://example.com/widget",
        "product_id": "W123",
    }

    client.post("/service/add_my_data", json=payload)
    delete_response = client.delete("/service/add_my_data/W123")
    get_response = client.get("/service/add_my_data?product_id=W123")

    assert delete_response.status_code == 200
    assert delete_response.get_json()["message"] == "product deleted"
    assert get_response.status_code == 200
    assert get_response.get_json()["products"] == []


def test_delete_product_not_found_returns_404(client):
    response = client.delete("/service/add_my_data/DOES_NOT_EXIST")

    assert response.status_code == 404
    assert response.get_json()["error"] == "product not found"
