#!/bin/bash

# ✅ Install Git LFS inside the Railway container
curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | bash
apt-get install git-lfs -y
git lfs install

# ✅ Pull the real LFS files
git lfs pull

# ✅ Start the bot
python bot.py
