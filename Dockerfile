FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -e .
COPY scripts ./scripts

EXPOSE 8080
CMD ["uvicorn", "engram.api:app", "--host", "0.0.0.0", "--port", "8080"]
