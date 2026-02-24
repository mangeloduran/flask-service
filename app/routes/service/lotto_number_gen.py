from flask import Blueprint, jsonify
from numpy import random


bp = Blueprint("lotto_number_gen", __name__, url_prefix="/service/lotto")   

@bp.route("/generate", methods=["GET"])
def generate_lotto_numbers():
    lotto_numbers = random.sample(range(1, 50), 6)
    return jsonify({"lotto_numbers": lotto_numbers})

@bp.route("/powerball", methods=["GET"])
def generate_powerball_numbers():
    main_numbers = random.choice(range(1, 70), 5, replace=False).tolist()
    powerball_number = random.randint(1, 26)
    return jsonify({"main_numbers": main_numbers, "powerball_number": powerball_number})

@bp.route("/euromillions", methods=["GET"])
def generate_euromillions_numbers():
    main_numbers = random.choice(range(1, 51), 5, replace=False).tolist()
    lucky_star_numbers = random.choice(range(1, 13), 2, replace=False).tolist()
    return jsonify({"main_numbers": main_numbers, "lucky_star_numbers": lucky_star_numbers})    

@bp.route("/mega_millions", methods=["GET"])
def generate_mega_millions_numbers():
    main_numbers = random.choice(range(1, 71), 5, replace=False).tolist()
    mega_ball_number = random.randint(1, 25)
    return jsonify({"main_numbers": main_numbers, "mega_ball_number": mega_ball_number})