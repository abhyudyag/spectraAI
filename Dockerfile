# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Install system dependencies (Git is required for the Indexer/Feedback loop)
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Install Google Cloud AI libraries
RUN pip install google-cloud-aiplatform

# Copy the rest of the application code
COPY . .

# Create necessary data directories with correct permissions
RUN mkdir -p data/vector_store data/sessions data/model_cache
RUN chmod -R 777 data

# Expose the Streamlit port
EXPOSE 8501

# Define environment variables
ENV PYTHONUNBUFFERED=1
ENV SPECTRA_LLM_PROVIDER="vertex"

# Healthcheck to ensure the container is responsive
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Run the application
ENTRYPOINT ["streamlit", "run", "interfaces/web/app.py", "--server.port=8501", "--server.address=0.0.0.0"]