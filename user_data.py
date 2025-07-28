# user_data.py
from tinydb import TinyDB, Query

db = TinyDB("user_data.json")
users_table = db.table("users")

def load_users():
    return set(user["id"] for user in users_table.all())

def add_user(user_ids_set, user_id):
    if user_id not in user_ids_set:
        users_table.insert({"id": user_id})
        user_ids_set.add(user_id)
    return True
