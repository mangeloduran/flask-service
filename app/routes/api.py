from flask import Blueprint, jsonify

bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.route("/example", methods=["GET"])
def example():
    return jsonify({"message": "hello"})
