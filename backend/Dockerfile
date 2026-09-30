FROM python:3.11-slim

WORKDIR /app

# build-essential/libffi-dev: necessários para compilar bcrypt/cryptography
# caso não haja wheel pré-compilada para a arquitetura da imagem
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
