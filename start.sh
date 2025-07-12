#!/bin/bash

# ✅ Clean up and clone the repo
rm -rf /app/code
git clone https://github.com/ogabek1106/voxi-bot.git /app/code

# ✅ Move into the cloned repo
cd /app/code

# ✅ Install Git LFS and pull actual files
apt-get update
apt-get install git-lfs -y
git lfs install
git lfs pull

# ✅ Run the bot
python bot.py
