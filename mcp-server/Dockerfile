FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

ARG TURNKEY_CLI_VERSION=v1.1.5

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates \
  && arch="$(dpkg --print-architecture)" \
  && case "$arch" in \
      amd64) tk_arch="x86_64" ;; \
      arm64) tk_arch="aarch64" ;; \
      *) echo "Unsupported architecture: $arch" && exit 1 ;; \
    esac \
  && curl -fsSL -o /usr/local/bin/turnkey "https://github.com/tkhq/tkcli/releases/download/${TURNKEY_CLI_VERSION}/turnkey.linux-${tk_arch}" \
  && chmod +x /usr/local/bin/turnkey \
  && /usr/local/bin/turnkey --version \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "server.py", "--http", "--port=8000"]
