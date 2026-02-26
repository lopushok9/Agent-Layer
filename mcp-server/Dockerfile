FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && npm i -g @turnkey/sdk-server \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "server.py", "--http", "--port=8000"]
