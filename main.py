import os
import json
import base64
import random
import datetime
from flask import Flask, request
from google.cloud import storage
from google.cloud import bigquery

app = Flask(__name__)

# Initialize clients (will use default credentials or service account credentials attached to Cloud Run)
try:
    storage_client = storage.Client()
except Exception as e:
    print(f"Warning: Storage client initialization failed (expected in local/test environments): {e}")
    storage_client = None

try:
    bq_client = bigquery.Client()
except Exception as e:
    print(f"Warning: BigQuery client initialization failed (expected in local/test environments): {e}")
    bq_client = None

# Read config from environment variables (with defaults)
BQ_DATASET = os.environ.get("BQ_DATASET", "document_processing")
BQ_TABLE = os.environ.get("BQ_TABLE", "metadata")

@app.route("/", methods=["POST"])
def process_pubsub_message():
    """Receives and processes Pub/Sub push messages triggered by Cloud Storage uploads."""
    envelope = request.get_json()
    if not envelope:
        msg = "No JSON payload received"
        print(f"Error: {msg}")
        return msg, 400

    if not isinstance(envelope, dict) or "message" not in envelope:
        msg = "Invalid Pub/Sub message format"
        print(f"Error: {msg}")
        return msg, 400

    pubsub_message = envelope["message"]
    attributes = pubsub_message.get("attributes", {})
    
    # Extract object info from attributes
    bucket = attributes.get("bucketId")
    object_name = attributes.get("objectId")
    event_type = attributes.get("eventType")

    # If attributes are missing, attempt to decode data body
    if "data" in pubsub_message and (not bucket or not object_name):
        try:
            data_payload = base64.b64decode(pubsub_message["data"]).decode("utf-8")
            data_json = json.loads(data_payload)
            bucket = bucket or data_json.get("bucket")
            object_name = object_name or data_json.get("name")
        except Exception as e:
            print(f"Error decoding data payload: {e}")

    print(f"Received event. EventType: {event_type}, Bucket: {bucket}, Object: {object_name}")

    # Process only finalized (uploaded) events
    if event_type and event_type != "OBJECT_FINALIZE":
        print(f"Ignoring non-upload event type: {event_type}")
        return f"Event type {event_type} ignored", 200

    if not bucket or not object_name:
        msg = "Bucket or Object name is missing from the message"
        print(f"Error: {msg}")
        return msg, 400

    try:
        # 1. Fetch object metadata and download content if necessary
        bucket_obj = storage_client.bucket(bucket)
        blob = bucket_obj.get_blob(object_name)
        if not blob:
            raise ValueError(f"Object {object_name} not found in bucket {bucket}")

        size = blob.size
        content_type = blob.content_type or "application/octet-stream"

        word_count = 0
        tags = []
        ocr_text_preview = ""

        # 2. Simulate OCR / Text Extraction
        if object_name.endswith(".txt"):
            print(f"Processing text file: {object_name}")
            try:
                # Download and decode text
                content = blob.download_as_text(encoding="utf-8")
                ocr_text_preview = content[:200]
                words = content.split()
                word_count = len(words)
                
                # Extract some simple tags (words > 4 chars, unique, alphanumeric)
                words_clean = [w.lower().strip(".,!?;:()\"'") for w in words]
                words_clean = [w for w in words_clean if len(w) > 4 and w.isalnum()]
                unique_words = sorted(list(set(words_clean)))
                tags = unique_words[:5]  # Limit to top 5
                tags.append("txt")
            except Exception as ex:
                print(f"Error reading file content as text: {ex}. Falling back to default mock OCR.")
                raise ex
        else:
            print(f"Simulating OCR for non-text file: {object_name}")
            # Mock OCR for other file extensions (PDF, image, docx, etc.)
            word_count = random.randint(50, 1500)
            ext = object_name.split(".")[-1] if "." in object_name else "unknown"
            tags = ["simulated-ocr", ext, "document"]
            ocr_text_preview = f"[Simulated OCR text preview for non-text file. Content-Type: {content_type}]"

        # 3. Stream Metadata to BigQuery
        project = bq_client.project
        table_id = f"{project}.{BQ_DATASET}.{BQ_TABLE}"

        row_to_insert = {
            "filename": object_name,
            "bucket": bucket,
            "size": size,
            "content_type": content_type,
            "word_count": word_count,
            "tags": tags,
            "ocr_text_preview": ocr_text_preview,
            "process_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        print(f"Streaming row to BigQuery ({table_id}): {json.dumps(row_to_insert)}")
        errors = bq_client.insert_rows_json(table_id, [row_to_insert])

        if errors:
            raise RuntimeError(f"BigQuery insert failed: {errors}")

        print(f"Successfully processed {object_name}")
        return "OK", 200

    except Exception as e:
        # Log error to stdout (Cloud Logging) and return HTTP 500 so Pub/Sub retries
        print(f"ERROR: Failed to process document {object_name} in bucket {bucket}: {e}")
        return f"Internal Server Error: {e}", 500

if __name__ == "__main__":
    # Run locally on port 8080 (Cloud Run default)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
