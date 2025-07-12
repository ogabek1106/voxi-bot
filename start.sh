#!/bin/bash

# ✅ Install Git LFS
curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | bash
apt-get install git-lfs -y
git lfs install

# ✅ Delete old code (if exists) and clone fresh
cd /app || exit
rm -rf code
git clone https://github.com/ogabek1106/voxi-bot.git code
cd code

# ✅ Initialize Git LFS inside the cloned repo and pull real files
git lfs install
git lfs pull

# ✅ Make sure PDFs are valid
echo "Contents of books/:"
ls -lh books/

# ✅ Run your bot
python bot.py
