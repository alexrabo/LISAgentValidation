FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source + pre-computed data
COPY app.py .
COPY verified_run_results.json .
COPY verified_run_decisions.json .

# Cloud Run sets PORT; Streamlit must bind to it
ENV PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -f http://localhost:${PORT}/_stcore/health || exit 1

CMD streamlit run app.py \
      --server.port=${PORT} \
      --server.address=0.0.0.0 \
      --server.headless=true \
      --browser.gatherUsageStats=false
