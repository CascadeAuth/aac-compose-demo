# The sample agent's image: Python, the AAC pairing-authentication library and
# the two example programs. Built locally by `./starter setup`; nothing from
# AAC's private source and no key material is ever copied into it.
FROM python:3.12-slim

ARG AAC_INVOKE_AUTH_VERSION=0.1.2
RUN python -m pip install --no-cache-dir \
      "aac-invoke-auth[fastapi]==${AAC_INVOKE_AUTH_VERSION}" \
      "uvicorn==0.52.4" \
      "httpx==0.28.1"

WORKDIR /app
COPY agent.py client.py /app/
RUN chmod 0444 /app/*.py

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The stack runs the container as the invoking user (compose.yaml); this is
# the fallback identity when the image is started any other way.
USER 65532:65532

CMD ["python", "-m", "uvicorn", "agent:app", "--host", "127.0.0.1", "--port", "8000"]
