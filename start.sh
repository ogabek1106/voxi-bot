#!/bin/bash

# ✅ Install Git LFS
curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | bash
apt-get install git-lfs -y
git lfs install

# ✅ Clone fresh copy inside /app/code if not already
cd /app || exit
rm -rf code
git clone https://github.com/ogabek1106/voxi-bot.git code
cd code

# ✅ Pull LFS files
git lfs pull

# ✅ Run the bot
python bot.py
