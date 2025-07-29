# ratings.py

import json
import os

RATINGS_FILE = "book_ratings.json"

def load_ratings():
    if not os.path.exists(RATINGS_FILE):
        return {}
    try:
        with open(RATINGS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_ratings(data):
    with open(RATINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_rating(book_code, user_id, score):
    ratings = load_ratings()
    if book_code not in ratings:
        ratings[book_code] = {}
    ratings[book_code][str(user_id)] = score
    save_ratings(ratings)

def has_rated(book_code, user_id):
    ratings = load_ratings()
    return str(user_id) in ratings.get(book_code, {})

def get_average_rating(book_code):
    ratings = load_ratings()
    book_ratings = ratings.get(book_code, {})
    if not book_ratings:
        return (0, 0)
    scores = list(book_ratings.values())
    avg = round(sum(scores) / len(scores), 2)
    return (avg, len(scores))
