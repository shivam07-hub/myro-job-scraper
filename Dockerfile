# Daily source poll on Railway: scrape -> resolve -> publish (no model inference).
# Embeddings and enrichment stay on the laptop (decided 2026-10-03); see docs/RAILWAY.md.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY scraper/requirements.txt scraper/requirements.txt
RUN pip install -r scraper/requirements.txt

COPY . .

# The pipeline writes run outputs and logs under the repo root. Point both at
# the Railway volume mounted at /data so they survive between daily runs.
RUN ln -s /data/All_CSV_Outputs /app/All_CSV_Outputs \
    && ln -s /data/logs /app/logs

CMD ["sh", "scraper/railway_poll.sh"]
