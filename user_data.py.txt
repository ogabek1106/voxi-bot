# user_data.py
import json
import os

# File paths
USER_FILE = "user_ids.json"
STATS_FILE = "book_stats.json"
RATING_FILE = "book_ratings.json"

# ------------------ USER TRACKING ------------------
def load_users():
    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r") as f:
            return json.load(f)
    return []

def save_users(user_ids):
    with open(USER_FILE, "w") as f:
        json.dump(user_ids, f)

def add_user(user_ids, user_id):
    if user_id not in user_ids:
        user_ids.append(user_id)
        save_users(user_ids)
        return True
    return False

# ------------------ BOOK REQUEST COUNTING ------------------
def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def increment_book_count(code):
    stats = load_stats()
    stats[code] = stats.get(code, 0) + 1
    save_stats(stats)

# ------------------ BOOK RATINGS ------------------
def load_rating_stats():
    if os.path.exists(RATING_FILE):
        with open(RATING_FILE, "r") as f:
            return json.load(f)
    return {}

def save_rating(user_id, book_code, rating):
    stats = load_rating_stats()
    if book_code not in stats:
        stats[book_code] = {str(i): 0 for i in range(1, 6)}
    stats[book_code][str(rating)] += 1

    if "votes" not in stats:
        stats["votes"] = {}
    if user_id not in stats["votes"]:
        stats["votes"][user_id] = []
    stats["votes"][user_id].append(book_code)

    with open(RATING_FILE, "w") as f:
        json.dump(stats, f)

def has_rated(user_id, book_code):
    stats = load_rating_stats()
    return user_id in stats.get("votes", {}) and book_code in stats["votes"][user_id]
