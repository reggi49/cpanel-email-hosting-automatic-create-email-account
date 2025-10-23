FROM python:3.12-slim

# opsional: percepat pip
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# default CMD diset dari compose (sleep infinity)
