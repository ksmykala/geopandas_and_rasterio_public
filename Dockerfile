FROM python:3.11-slim

# rasterio wheels bundle GDAL, but GDAL needs libexpat from the system (missing in slim)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]
