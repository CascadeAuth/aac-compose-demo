# The sample agent's image: Python, AAC's pairing-authentication library and
# the two example programs. `./demo up` builds it on your machine.
FROM python:3.12-slim
ARG AAC_INVOKE_AUTH_VERSION
RUN pip install --no-cache-dir "aac-invoke-auth[fastapi]==${AAC_INVOKE_AUTH_VERSION}" "uvicorn==0.52.4" "httpx==0.28.1"
WORKDIR /app
COPY agent.py client.py ./
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "agent:app", "--host", "127.0.0.1", "--port", "8000"]
