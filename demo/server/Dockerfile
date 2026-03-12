FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install lis-triage-engine from local wheel
# KG (clinical_knowledge.json) is NOT baked in — injected at runtime via KG_JSON_B64
COPY ../wheels/lis_triage_engine-1.0.0-py3-none-any.whl /tmp/
RUN pip install --no-cache-dir /tmp/lis_triage_engine-1.0.0-py3-none-any.whl

# Copy server package
COPY . /app/server/
COPY ../config/clinical_knowledge.SAMPLE.json /app/config/

# Runtime config — real KG injected via KG_JSON_B64 env var
ENV DB_PATH=/app/data/lims.db
ENV KG_PATH=/app/config/clinical_knowledge.json

# Data directory for lims.db — mount a volume here in docker-compose
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "server.lims_server:app", "--host", "0.0.0.0", "--port", "8000"]
