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
        try:
            with open(STATS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"[load_stats ERROR] {e}")
    return {}
