FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000

# Let the process honor Railway's injected PORT instead of pinning 8000.
CMD ["python", "server.py", "--http"]
