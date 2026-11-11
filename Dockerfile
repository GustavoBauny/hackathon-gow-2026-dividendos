# Imagem da solução: pipeline, testes e explicador.
FROM python:3.14-slim

# LightGBM precisa do runtime do OpenMP
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# tolera checkout com CRLF (Windows) e sem bit de execução
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh
COPY src/ src/
COPY tests/ tests/
COPY *.py ./

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "gerar_decisoes.py"]
