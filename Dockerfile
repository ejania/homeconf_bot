FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if any are needed (sqlite3 is built-in to python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the database file is in a volume for persistence
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
