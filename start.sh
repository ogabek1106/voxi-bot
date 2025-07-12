#!/bin/bash

# ✅ Install Git LFS
curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | bash
apt-get install git-lfs -y
git lfs install

# ✅ Clone the full repo to get real LFS files
cd /app
rm -rf code
git clone https://github.com/ogabek1106/voxi-bot.git code
cd code
git lfs pull

# ✅ Start the bot
python bot.py
