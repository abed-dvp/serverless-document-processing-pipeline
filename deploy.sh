#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "============================================================"
echo "Starting deployment of Document Processing Pipeline..."
echo "============================================================"

# Configure variables (Defaults can be overridden by environment variables)
PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo "")}
REGION=${REGION:-"us-central1"}
REPO_NAME=${REPO_NAME:-"document-pipeline-repo"}
SERVICE_NAME=${SERVICE_NAME:-"document-processor"}
TOPIC_NAME=${TOPIC_NAME:-"document-uploads"}
SUBSCRIPTION_NAME=${SUBSCRIPTION_NAME:-"document-uploads-sub"}
DATASET_NAME=${DATASET_NAME:-"document_processing"}
TABLE_NAME=${TABLE_NAME:-"metadata"}

# Ensure Project ID is available
if [ -z "$PROJECT_ID" ]; then
  echo "ERROR: GCP Project ID could not be auto-detected."
  echo "Please set the PROJECT_ID environment variable or configure gcloud:"
  echo "  export PROJECT_ID=\"your-project-id\""
  echo "  ./deploy.sh"
  exit 1
fi

BUCKET_NAME=${BUCKET_NAME:-"${PROJECT_ID}-documents"}

echo "Project ID:        $PROJECT_ID"
echo "Region:            $REGION"
echo "Storage Bucket:    gs://$BUCKET_NAME"
echo "Pub/Sub Topic:     $TOPIC_NAME"
echo "Pub/Sub Sub:       $SUBSCRIPTION_NAME"
echo "BigQuery Table:    $DATASET_NAME.$TABLE_NAME"
echo "Cloud Run Service: $SERVICE_NAME"
echo "Artifact Registry: $REPO_NAME"
echo "------------------------------------------------------------"

# 1. Enable GCP Services
echo "1. Enabling required Google Cloud APIs..."
gcloud services enable \
  run.googleapis.com \
  pubsub.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com

# 2. Create Artifact Registry repository
echo "2. Checking/Creating Artifact Registry repository '$REPO_NAME' in '$REGION'..."
if ! gcloud artifacts repositories describe "$REPO_NAME" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Docker repository for document processing pipeline"
else
  echo "   Repository already exists."
fi

# 3. Create Cloud Storage Bucket
echo "3. Checking/Creating GCS bucket 'gs://$BUCKET_NAME'..."
if ! gsutil ls -b "gs://$BUCKET_NAME" >/dev/null 2>&1; then
  # Make bucket in the selected region
  gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://$BUCKET_NAME"
else
  echo "   Bucket already exists."
fi

# 4. Create Pub/Sub Topic
echo "4. Checking/Creating Pub/Sub Topic '$TOPIC_NAME'..."
if ! gcloud pubsub topics describe "$TOPIC_NAME" >/dev/null 2>&1; then
  gcloud pubsub topics create "$TOPIC_NAME"
else
  echo "   Topic already exists."
fi

# 5. Grant Storage Service Account Publisher access on the Topic
echo "5. Granting Storage service agent Publisher permissions on the topic..."
STORAGE_SA=$(gsutil kms serviceaccount -p "$PROJECT_ID")
gcloud pubsub topics add-iam-policy-binding "$TOPIC_NAME" \
  --member="serviceAccount:$STORAGE_SA" \
  --role="roles/pubsub.publisher"

# 6. Create GCS notification subscription targeting the topic
echo "6. Setting up Cloud Storage notification trigger..."
# Check if a notification already exists, if not, create it
if [ "$(gsutil notification list "gs://$BUCKET_NAME" 2>&1 | grep -c "Notification configuration")" -eq 0 ]; then
  gsutil notification create -f json -t "$TOPIC_NAME" "gs://$BUCKET_NAME"
else
  echo "   Storage notifications already configured."
fi

# 7. Create BigQuery Dataset and Table
echo "7. Creating BigQuery dataset '$DATASET_NAME' and table '$TABLE_NAME'..."
if ! bq --project_id="$PROJECT_ID" show "$DATASET_NAME" >/dev/null 2>&1; then
  bq --project_id="$PROJECT_ID" mk --dataset --location="$REGION" "$DATASET_NAME"
else
  echo "   Dataset already exists."
fi

if ! bq --project_id="$PROJECT_ID" show "$DATASET_NAME.$TABLE_NAME" >/dev/null 2>&1; then
  bq --project_id="$PROJECT_ID" mk --table \
    "$DATASET_NAME.$TABLE_NAME" \
    schema.json
else
  echo "   Table already exists."
fi

# 8. Build and Deploy Cloud Run Service
echo "8. Building container image and deploying to Cloud Run..."
IMAGE_URL="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$SERVICE_NAME:latest"

# Build image using Cloud Build
gcloud builds submit --tag "$IMAGE_URL" .

# Deploy to Cloud Run (Unauthenticated / Public access allowed)
gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE_URL" \
  --platform=managed \
  --region="$REGION" \
  --allow-unauthenticated \
  --update-env-vars BQ_DATASET="$DATASET_NAME",BQ_TABLE="$TABLE_NAME"

# Get the URL of the deployed Cloud Run service
RUN_URL=$(gcloud run services describe "$SERVICE_NAME" --platform=managed --region="$REGION" --format="value(status.url)")
echo "   Cloud Run service URL: $RUN_URL"

# 9. Create Pub/Sub Push Subscription targeting Cloud Run
echo "9. Setting up Pub/Sub Push Subscription targeting Cloud Run..."
if ! gcloud pubsub subscriptions describe "$SUBSCRIPTION_NAME" >/dev/null 2>&1; then
  gcloud pubsub subscriptions create "$SUBSCRIPTION_NAME" \
    --topic="$TOPIC_NAME" \
    --push-endpoint="$RUN_URL" \
    --ack-deadline=60
else
  echo "   Updating existing push subscription endpoint to: $RUN_URL"
  gcloud pubsub subscriptions update "$SUBSCRIPTION_NAME" \
    --push-endpoint="$RUN_URL"
fi

echo "============================================================"
echo "Deployment successful!"
echo "To test the pipeline in the cloud, run:"
echo "  export PROJECT_ID=\"$PROJECT_ID\""
echo "  export BUCKET_NAME=\"$BUCKET_NAME\""
echo "  python test_cloud.py"
echo "============================================================"
