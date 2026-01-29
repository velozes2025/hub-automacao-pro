FROM python:3.11-slim

WORKDIR /opt/hub

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source as 'app' package
COPY . ./app/

EXPOSE 3000

CMD ["python", "-m", "app"]
