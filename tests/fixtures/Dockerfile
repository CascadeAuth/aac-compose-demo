FROM aac-compose-demo-agent:local
RUN pip install --no-cache-dir "cryptography==50.0.1"
WORKDIR /fixture
COPY wire.py run.py ./
ENTRYPOINT ["python", "run.py"]
