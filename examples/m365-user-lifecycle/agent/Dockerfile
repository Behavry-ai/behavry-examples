FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY m365_lifecycle ./m365_lifecycle

RUN useradd --uid 10001 --no-create-home agent
USER agent

EXPOSE 8080
# One worker, one replica: in-flight requests are tracked in memory.
CMD ["uvicorn", "m365_lifecycle.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
