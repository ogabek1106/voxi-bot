import os
import json

RATINGS_FILE = "book_ratings.json"

def load_ratings():
    if os.path.exists(RATINGS_FILE):
        try:
            with open(RATINGS_FILE, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except:
            return {}
    return {}

def save_ratings(data):
    with open(RATINGS_FILE, "w") as f:
        json.dump(data, f)

def add_rating(book_code, score):
    data = load_ratings()
    if book_code not in data:
        data[book_code] = []
    data[book_code].append(score)
    save_ratings(data)

def get_average_rating(book_code):
    data = load_ratings()
    ratings = data.get(book_code, [])
    if ratings:
        avg = sum(ratings) / len(ratings)
        return round(avg, 2), len(ratings)
    return None, 0
