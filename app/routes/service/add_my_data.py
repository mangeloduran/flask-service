import sqlite3
from pathlib import Path
from flask import Blueprint, request, jsonify

bp = Blueprint("add_my_data", __name__, url_prefix="/service/add_my_data")

DB_PATH = Path(__file__).resolve().parent / "products.db"


def _get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize_table():
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor TEXT NOT NULL,
            product_name TEXT NOT NULL,
            url TEXT NOT NULL,
            product_id TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.commit()
    connection.close()


_initialize_table()


@bp.route("", methods=["POST"])
def create_product():
    payload = request.get_json(silent=True) or {}

    required_fields = ["vendor", "product_name", "url", "product_id"]
    missing = [field for field in required_fields if not payload.get(field)]
    if missing:
        return (
            jsonify({"error": f"Missing required fields: {', '.join(missing)}"}),
            400,
        )

    try:
        connection = _get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO products (vendor, product_name, url, product_id)
            VALUES (?, ?, ?, ?)
            """,
            (
                payload["vendor"],
                payload["product_name"],
                payload["url"],
                payload["product_id"],
            ),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "product_id already exists"}), 409
    finally:
        connection.close()

    return jsonify({"message": "product saved"}), 201


@bp.route("", methods=["GET"])
def get_products():
    product_id = request.args.get("product_id")

    connection = _get_connection()
    cursor = connection.cursor()
    if product_id:
        cursor.execute(
            """
            SELECT vendor, product_name, url, product_id
            FROM products
            WHERE product_id = ?
            """,
            (product_id,),
        )
    else:
        cursor.execute(
            """
            SELECT vendor, product_name, url, product_id
            FROM products
            ORDER BY id DESC
            """
        )

    rows = cursor.fetchall()
    connection.close()

    products = [dict(row) for row in rows]
    return jsonify({"products": products}), 200


@bp.route("/<string:product_id>", methods=["DELETE"])
def delete_product(product_id):
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
    connection.commit()
    deleted_count = cursor.rowcount
    connection.close()

    if deleted_count == 0:
        return jsonify({"error": "product not found"}), 404

    return jsonify({"message": "product deleted"}), 200