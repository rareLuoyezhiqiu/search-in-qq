FROM python:3.13-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home collector
COPY . .
RUN mkdir /data && chown collector:collector /data
USER collector
ENV DATA_DIR=/data
CMD ["uvicorn", "collector.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
