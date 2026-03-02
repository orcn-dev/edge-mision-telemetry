FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ai_service.py .
EXPOSE 9101
CMD ["python", "ai_service.py"]