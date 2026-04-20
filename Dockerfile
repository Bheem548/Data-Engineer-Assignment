FROM python:3.11-slim

WORKDIR /app

COPY transform.py .

RUN pip install boto3

CMD ["python", "transform.py"]