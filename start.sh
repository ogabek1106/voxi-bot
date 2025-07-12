#!/bin/bash

# ✅ Install Git LFS inside the Railway container
curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | bash
apt-get install git-lfs -y
git lfs install

# ✅ Re-clone the repo with LFS support
cd /tmp
git clone https://github.com/ogabek1106/voxi-bot.git
cd voxi-bot
git lfs pull

# ✅ Start the bot
python bot.py
