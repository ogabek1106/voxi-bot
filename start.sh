#!/bin/bash

# Install Git LFS
apt update && apt install -y git-lfs

# Setup and pull LFS files
git lfs install
git lfs pull

# Start the bot
python bot.py
