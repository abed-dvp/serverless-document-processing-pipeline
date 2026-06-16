import unittest
from unittest.mock import MagicMock
import json
import base64

# Import main (which catches auth errors and doesn't crash)
import main

class TestDocumentProcessor(unittest.TestCase):
    def setUp(self):
        # Enable testing configuration
        main.app.testing = True
        self.client = main.app.test_client()
        
        # Override storage and BigQuery clients with mocks
        main.storage_client = MagicMock()
        main.bq_client = MagicMock()

    def test_process_text_file(self):
        """Test processing a text file: verifies content is read, word count is exact, and tags are extracted."""
        # 1. Mock GCS bucket and blob download
        mock_blob = MagicMock()
        mock_blob.size = 125
        mock_blob.content_type = "text/plain"
        mock_blob.download_as_text.return_value = "The quick brown fox jumps over the lazy dog. Python is a wonderful programming language."
        main.storage_client.bucket.return_value.get_blob.return_value = mock_blob

        # 2. Mock BigQuery responses
        main.bq_client.insert_rows_json.return_value = []
        main.bq_client.project = "test-gcp-project"

        # 3. Simulate Pub/Sub notification
        envelope = {
            "message": {
                "attributes": {
                    "bucketId": "my-documents-bucket",
                    "objectId": "sample_document.txt",
                    "eventType": "OBJECT_FINALIZE"
                }
            }
        }

        response = self.client.post("/", json=envelope)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode(), "OK")

        # 4. Assert GCS interactions
        main.storage_client.bucket.assert_called_with("my-documents-bucket")
        main.storage_client.bucket().get_blob.assert_called_with("sample_document.txt")
        mock_blob.download_as_text.assert_called_once()

        # 5. Assert BigQuery insertion and payload structure
        main.bq_client.insert_rows_json.assert_called_once()
        args, _ = main.bq_client.insert_rows_json.call_args
        
        # Check insert table name
        self.assertEqual(args[0], "test-gcp-project.document_processing.metadata")
        
        # Check rows payload
        inserted_row = args[1][0]
        self.assertEqual(inserted_row["filename"], "sample_document.txt")
        self.assertEqual(inserted_row["bucket"], "my-documents-bucket")
        self.assertEqual(inserted_row["size"], 125)
        self.assertEqual(inserted_row["content_type"], "text/plain")
        
        # Word count checks: "The quick brown fox jumps over the lazy dog. Python is a wonderful programming language."
        # words: ['The', 'quick', 'brown', 'fox', 'jumps', 'over', 'the', 'lazy', 'dog.', 'Python', 'is', 'a', 'wonderful', 'programming', 'language.'] (15 words)
        self.assertEqual(inserted_row["word_count"], 15)
        
        # Tag checks: words > 4 chars, sorted, unique, max 5, plus "txt"
        # words > 4: 'quick', 'brown', 'jumps', 'wonderful', 'programming' (cleaned: quick, brown, jumps, wonderful, programming)
        # Expected sorted: brown, jumps, programming, quick, wonderful + txt
        self.assertIn("brown", inserted_row["tags"])
        self.assertIn("jumps", inserted_row["tags"])
        self.assertIn("programming", inserted_row["tags"])
        self.assertIn("txt", inserted_row["tags"])
        self.assertEqual(len(inserted_row["tags"]), 6)
        
        self.assertTrue(inserted_row["ocr_text_preview"].startswith("The quick brown"))
        self.assertIsNotNone(inserted_row["process_timestamp"])

    def test_process_pdf_file_simulated(self):
        """Test processing a PDF file: verifies it falls back to simulated OCR logic."""
        mock_blob = MagicMock()
        mock_blob.size = 204800
        mock_blob.content_type = "application/pdf"
        main.storage_client.bucket.return_value.get_blob.return_value = mock_blob

        main.bq_client.insert_rows_json.return_value = []
        main.bq_client.project = "test-gcp-project"

        envelope = {
            "message": {
                "attributes": {
                    "bucketId": "my-documents-bucket",
                    "objectId": "reports/quarterly.pdf",
                    "eventType": "OBJECT_FINALIZE"
                }
            }
        }

        response = self.client.post("/", json=envelope)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode(), "OK")

        # Verify BigQuery insertion for PDF simulated metadata
        args, _ = main.bq_client.insert_rows_json.call_args
        inserted_row = args[1][0]
        self.assertEqual(inserted_row["filename"], "reports/quarterly.pdf")
        self.assertEqual(inserted_row["content_type"], "application/pdf")
        self.assertIn("simulated-ocr", inserted_row["tags"])
        self.assertIn("pdf", inserted_row["tags"])
        self.assertTrue(50 <= inserted_row["word_count"] <= 1500)
        self.assertIn("Simulated OCR text preview", inserted_row["ocr_text_preview"])

    def test_ignore_non_finalize_events(self):
        """Test that events other than OBJECT_FINALIZE are ignored and return HTTP 200."""
        envelope = {
            "message": {
                "attributes": {
                    "bucketId": "my-documents-bucket",
                    "objectId": "reports/quarterly.pdf",
                    "eventType": "OBJECT_DELETE"
                }
            }
        }

        response = self.client.post("/", json=envelope)
        self.assertEqual(response.status_code, 200)
        self.assertIn("ignored", response.data.decode())
        
        # Verify no calls to GCS or BQ were made
        main.storage_client.bucket.assert_not_called()
        main.bq_client.insert_rows_json.assert_not_called()

    def test_missing_elements_error(self):
        """Test that missing attributes result in a 400 Bad Request."""
        envelope = {
            "message": {
                "attributes": {
                    "eventType": "OBJECT_FINALIZE"
                }
            }
        }

        response = self.client.post("/", json=envelope)
        self.assertEqual(response.status_code, 400)
        self.assertIn("missing", response.data.decode().lower())

    def test_fail_fast_returns_500(self):
        """Test that failure in processing triggers a 500 Internal Server Error (for Pub/Sub retry)."""
        # Make storage download throw an error
        mock_blob = MagicMock()
        mock_blob.size = 10
        mock_blob.content_type = "text/plain"
        mock_blob.download_as_text.side_effect = Exception("Connection Reset")
        main.storage_client.bucket.return_value.get_blob.return_value = mock_blob

        envelope = {
            "message": {
                "attributes": {
                    "bucketId": "my-documents-bucket",
                    "objectId": "broken.txt",
                    "eventType": "OBJECT_FINALIZE"
                }
            }
        }

        response = self.client.post("/", json=envelope)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Internal Server Error", response.data.decode())

if __name__ == "__main__":
    unittest.main()
