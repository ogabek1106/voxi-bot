import json
import os

# File paths
USER_FILE = "user_ids.json"
STATS_FILE = "book_stats.json"

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
