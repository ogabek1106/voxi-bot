# user_data.py

import json
import os
from config import USER_FILE

def load_users():
    if not os.path.exists(USER_FILE):
        return None  # File not found
    try:
        with open(USER_FILE, "r") as f:
            return set(json.load(f))
    except json.JSONDecodeError:
        return set()  # Corrupted file, fallback to empty set

def save_users(user_ids):
    with open(USER_FILE, "w") as f:
        json.dump(list(user_ids), f)

def add_user(user_ids, user_id):
    if user_ids is None:
        return False
    if user_id not in user_ids:
        user_ids.add(user_id)
        save_users(user_ids)
        return True
    return False
