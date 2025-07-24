import chromadb
import uuid
import os

# Get ChromaDB connection from environment variables
CHROMA_HOST = os.getenv('CHROMA_HOST', 'localhost')
CHROMA_PORT = int(os.getenv('CHROMA_PORT', '8000'))

client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

# A successful client object creation means we can likely connect.
# Let's test the connection by trying to use it.
print("✅ ChromaDB client initialized.")

try:
    # 2. Create or get a collection
    collection_name = "my_test_collection"
    print(f"\nAttempting to get or create collection: '{collection_name}'")
    collection = client.get_or_create_collection(name=collection_name)
    print("✅ Collection is ready.")

    # 3. Add some documents to the collection
    print("\nAdding documents to the collection...")
    documents_to_add = [
        "The sky is blue.",
        "The ocean is vast and deep.",
        "Apples are a type of fruit.",
        "Cars are a common form of transportation.",
        "The sun is a star at the center of our solar system."
    ]
    ids_to_add = [str(uuid.uuid4()) for _ in documents_to_add]

    collection.add(
        documents=documents_to_add,
        ids=ids_to_add
    )
    print(f"✅ Added/updated documents. Collection now has {collection.count()} documents.")

    # 4. Query the collection to find similar documents
    query_text = "What color is the sky?"
    print(f"\nPerforming a query: '{query_text}'")

    results = collection.query(
        query_texts=[query_text],
        n_results=2
    )

    print("\n🔍 Query Results:")
    if results and results['documents']:
        for doc in results['documents'][0]:
            print(f"  - '{doc}'")
    else:
        print("No results found.")

    print("\n🎉 ChromaDB test completed successfully!")

except Exception as e:
    print(f"\n❌ An error occurred while interacting with the collection: {e}")