import os
import sys
import time
import uuid
import datetime
import subprocess
from google.cloud import storage
from google.cloud import bigquery
from google.oauth2.credentials import Credentials

def main():
    print("=== Cloud Integration Test ===")
    
    # Read configuration from environment or arguments
    project_id = os.environ.get("GCP_PROJECT") or os.environ.get("PROJECT_ID")
    bucket_name = os.environ.get("BUCKET_NAME")
    dataset_id = os.environ.get("BQ_DATASET", "document_processing")
    table_id = os.environ.get("BQ_TABLE", "metadata")

    if not project_id or not bucket_name:
        print("Error: Missing required environment variables.")
        print("Please set: PROJECT_ID (or GCP_PROJECT) and BUCKET_NAME")
        print("\nExample:")
        print("  export PROJECT_ID=\"your-project-id\"")
        print("  export BUCKET_NAME=\"your-gcs-bucket-name\"")
        print("  python test_cloud.py")
        sys.exit(1)

    print(f"Project ID: {project_id}")
    print(f"GCS Bucket: {bucket_name}")
    print(f"BQ Table:   {project_id}.{dataset_id}.{table_id}")

    # Initialize Google Cloud clients
    storage_client = None
    bq_client = None
    try:
        # Try default credential resolution first (e.g. ADC)
        storage_client = storage.Client(project=project_id)
        bq_client = bigquery.Client(project=project_id)
        print("Successfully authenticated using Application Default Credentials.")
    except Exception as default_err:
        print(f"ADC not found ({default_err}). Attempting to fetch access token from active gcloud configuration...")
        try:
            # Common paths for gcloud CLI
            gcloud_paths = [
                "gcloud",
                r"C:\Users\GOLD\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
                r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
            ]
            token = None
            for path in gcloud_paths:
                try:
                    token = subprocess.check_output([path, "auth", "print-access-token"], stderr=subprocess.DEVNULL, text=True).strip()
                    if token:
                        break
                except Exception:
                    continue
            
            if not token:
                raise ValueError("Could not obtain access token from gcloud CLI. Is 'gcloud' logged in?")
            
            credentials = Credentials(token)
            storage_client = storage.Client(project=project_id, credentials=credentials)
            bq_client = bigquery.Client(project=project_id, credentials=credentials)
            print("Successfully authenticated using gcloud access token.")
        except Exception as fallback_err:
            print(f"Failed to initialize GCP clients via gcloud fallback: {fallback_err}")
            print("Please verify you are logged in via 'gcloud auth login' and 'gcloud config set project'")
            sys.exit(1)

    # 1. Create a unique filename and content
    test_id = str(uuid.uuid4())[:8]
    filename = f"integration_test_{test_id}.txt"
    content = "Hello cloud pipeline world! This is a test file for the event-driven document processing pipeline."
    # Word count: 15 words
    expected_word_count = 15

    print(f"\n1. Creating local temporary file '{filename}' with content:")
    print(f"   \"{content}\"")

    # 2. Upload file to GCS
    print(f"\n2. Uploading '{filename}' to bucket '{bucket_name}'...")
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_string(content, content_type="text/plain")
        print("   Upload completed successfully!")
    except Exception as e:
        print(f"   Failed to upload file to GCS: {e}")
        sys.exit(1)

    # 3. Wait for the asynchronous pipeline to run
    wait_seconds = 10
    print(f"\n3. Waiting {wait_seconds} seconds for the event-driven pipeline to process...")
    for i in range(wait_seconds, 0, -1):
        sys.stdout.write(f"\r   Time remaining: {i}s ")
        sys.stdout.flush()
        time.sleep(1)
    print("\r   Waiting completed.              ")

    # 4. Query BigQuery for the metadata record
    print(f"\n4. Querying BigQuery table `{project_id}.{dataset_id}.{table_id}` for processed metadata...")
    query = f"""
        SELECT filename, bucket, size, content_type, word_count, tags, ocr_text_preview, process_timestamp
        FROM `{project_id}.{dataset_id}.{table_id}`
        WHERE filename = @filename
        LIMIT 1
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("filename", "STRING", filename)
        ]
    )

    try:
        query_job = bq_client.query(query, job_config=job_config)
        rows = list(query_job.result())

        if len(rows) == 0:
            print("   ERROR: No metadata record found in BigQuery! Check Cloud Run logs for errors.")
            sys.exit(1)

        row = rows[0]
        print("\n=== Success! Metadata Record Found ===")
        print(f"Filename:          {row.filename}")
        print(f"Bucket:            {row.bucket}")
        print(f"Size (bytes):      {row.size}")
        print(f"Content Type:      {row.content_type}")
        print(f"Word Count:        {row.word_count} (Expected: {expected_word_count})")
        print(f"Tags:              {row.tags}")
        print(f"Text Preview:      {row.ocr_text_preview}")
        print(f"Process Timestamp: {row.process_timestamp}")
        print("=======================================")

        # Double check values
        if row.word_count != expected_word_count:
            print(f"Warning: Word count mismatch! Got {row.word_count}, expected {expected_word_count}.")
        
        print("\nIntegration test completed successfully!")

    except Exception as e:
        print(f"   Failed to query BigQuery: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
