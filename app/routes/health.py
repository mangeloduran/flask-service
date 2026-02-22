from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.route("/healthz")
def liveness():
    return jsonify({"status": "ok"})


@bp.route("/readyz")
def readiness():
    return jsonify({"status": "ready"})
