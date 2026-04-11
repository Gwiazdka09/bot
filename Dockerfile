# Wykorzystujemy obraz z preinstalowanym Playwrightem i Pythonem
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

# Ustawienia środowiska
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH /app/src

WORKDIR /app

# Instalacja podstawowych narzędzi systemowych
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Instalacja uv (szybszy manager pakietów)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Kopiowanie plików definicji zależności
COPY pyproject.toml ./

# Instalacja zależności (bez samego projektu jeszcze)
RUN uv pip install --system ".[ai,scraper]"

# Kopiowanie reszty kodu projektu
COPY src ./src
COPY data ./data

# Instalacja Playwright browsers (tylko Chromium dla oszczędności miejsca)
RUN playwright install chromium

# Skrypt startowy
COPY start_cloud.sh ./
RUN chmod +x start_cloud.sh

# Domyślna komenda (może być nadpisana w Cloud Scheduler)
CMD ["./start_cloud.sh"]
