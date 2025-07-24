import os
from ragflow_sdk import RAGFlow
import time

# --- Configuration ---
# Replace with your actual API Key from the RAGFlow UI
API_KEY = "your-ragflow-api-key-goes-here"
# This is the default address for the RAGFlow service you started in Docker
RAGFLOW_API_BASE = os.getenv('RAGFLOW_API_URL', 'http://localhost:9380')

# Check if the API key has been replaced
if "your-ragflow-api-key" in API_KEY:
    print("❌ ERROR: Please replace 'your-ragflow-api-key-goes-here' with your actual API key.")
    exit()

# --- Initialize RAGFlow Client ---
try:
    api = RAGFlow(api_key=API_KEY, api_base=RAGFLOW_API_BASE)
    print("✅ Successfully initialized RAGFlow client.")
except Exception as e:
    print(f"❌ Failed to initialize RAGFlow client: {e}")
    exit()

# --- 1. Upload a document to the knowledge base ---
file_path = "test_document.txt"
print(f"\nUploading document: '{file_path}'...")

try:
    # upload_document returns a dictionary with the process result
    upload_result = api.upload_document(file_path)
    # The result contains a 'doc_id' which we can use to track progress
    doc_id = upload_result.get('data', {}).get('doc_ids', [None])[0]

    if doc_id:
        print(f"✅ Document uploaded successfully. Doc ID: {doc_id}")
        # Wait a few seconds for RAGFlow to process the document
        print("Waiting for processing...")
        time.sleep(10)
    else:
        print(f"❌ Document upload failed. Response: {upload_result}")
        exit()

except Exception as e:
    print(f"❌ An error occurred during document upload: {e}")
    exit()


# --- 2. Start a conversation and ask a question ---
print("\nStarting a new conversation...")
try:
    question = "What is Mars commonly called?"
    print(f"❓ Asking question: '{question}'")

    # The chat method streams the response. We'll collect the chunks.
    response_generator = api.chat(question=question)

    full_response = ""
    for chunk in response_generator:
        full_response += chunk

    print("\n💡 RAGFlow's Answer:")
    print(full_response)
    print("\n🎉 Test completed successfully!")

except Exception as e:
    print(f"❌ An error occurred during chat: {e}")
