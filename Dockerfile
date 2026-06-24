FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (IMPORTANT for yt-dlp + bcrypt)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better caching)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# Expose Flask port
EXPOSE 5000

# Run app
CMD ["python", "app.py"]