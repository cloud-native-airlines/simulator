FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml requirements.txt ./
RUN pip install -r requirements.txt

COPY src ./src
RUN pip install --no-deps .

EXPOSE 8000
# Bind to all interfaces inside the container; override with SIM_PORT if needed.
ENV SIM_HOST=0.0.0.0 SIM_PORT=8000
CMD ["python", "-m", "simulator"]
