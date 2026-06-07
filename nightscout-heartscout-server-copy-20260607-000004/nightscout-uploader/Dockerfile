FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY librelinkup_to_nightscout.py .
CMD ["python", "/app/librelinkup_to_nightscout.py"]
