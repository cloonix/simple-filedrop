FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app/ .
RUN mkdir -p uploads data
EXPOSE 8000
CMD ["python", "main.py"]