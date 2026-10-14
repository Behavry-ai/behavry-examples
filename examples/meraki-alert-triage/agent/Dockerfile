FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY meraki_triage ./meraki_triage

RUN useradd --uid 10001 --no-create-home agent
USER agent

EXPOSE 8080
# One worker, one replica: the noise gate keeps its state in memory.
CMD ["uvicorn", "meraki_triage.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
