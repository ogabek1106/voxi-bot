# Dockerfile — minimal image to run your polling bot
FROM python:3.11-slim

# avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# copy only what we need early (speeds builds)
COPY requirements.txt .

# install deps
RUN pip install --no-cache-dir -r requirements.txt

# copy rest of repo
COPY . .

# ensure persistent DB dir exists (Railway uses /data)
ENV DB_PATH=/data/data.db
RUN mkdir -p /data

# run the bot
CMD ["python", "bot.py"]
