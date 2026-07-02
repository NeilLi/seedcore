from __future__ import annotations

from datetime import datetime

from seedcore.models.rag import (
    ACLSnapshot,
    DocumentSource,
    RAGCandidateChunk,
    RAGChunk,
    RAGDocument,
)

CONTROLLED_DOCUMENTS = [
    {
        "id": "doc-public-1",
        "text": "SeedCore zero-trust RCT execution boundary tokenizes actions.",
        "classification": "public",
        "ref": "docstore://public-1",
    },
    {
        "id": "doc-confidential-1",
        "text": "Confidential facility operator co-signature requirement rules.",
        "classification": "confidential",
        "ref": "docstore://confidential-1",
    },
    {
        "id": "doc-restricted-1",
        "text": "Restricted transaction audit logs and KMS secret keys.",
        "classification": "restricted",
        "ref": "docstore://restricted-1",
    },
]


class ControlledRetriever:
    """Mock controlled-source retrieval adapter for tests and local drills."""

    def __init__(self, index_snapshot_ref: str = "index-snapshot-1") -> None:
        self.index_snapshot_ref = index_snapshot_ref
        self._text_by_ref = {
            self._text_ref(doc_data["id"]): doc_data["text"]
            for doc_data in CONTROLLED_DOCUMENTS
        }

    def retrieve_candidates(
        self,
        query: str,
        retrieved_at: datetime,
        retriever_version: str = "fixture-retriever.v1",
    ) -> list[RAGCandidateChunk]:
        """
        Query the mock document store and return matching candidate chunks.
        If query is empty, return all mock documents as candidates.
        """
        candidates: list[RAGCandidateChunk] = []
        query_words = [word.lower().strip() for word in query.split() if word.strip()]

        for doc_data in CONTROLLED_DOCUMENTS:
            match = False
            if not query_words:
                match = True
            else:
                match = any(word in doc_data["text"].lower() for word in query_words)

            if match:
                acl = ACLSnapshot(
                    acl_snapshot_id=f"acl-{doc_data['id']}",
                    acl_snapshot_hash=f"acl-hash-{doc_data['id']}",
                    source_system="fixture-retriever",
                    captured_at=retrieved_at,
                )
                document = RAGDocument(
                    document_id=doc_data["id"],
                    document_hash=f"hash-{doc_data['id']}",
                    source=DocumentSource(
                        source_id="source-1",
                        source_type="document_store",
                        source_ref=doc_data["ref"],
                    ),
                    acl_snapshot=acl,
                    classification=doc_data["classification"],
                )
                chunk = RAGChunk(
                    chunk_id=f"chunk-{doc_data['id']}",
                    document_id=doc_data["id"],
                    chunk_hash=f"chunk-hash-{doc_data['id']}",
                    ordinal=0,
                    text_ref=self._text_ref(doc_data["id"]),
                    acl_snapshot=acl,
                )
                candidates.append(
                    RAGCandidateChunk(
                        document=document,
                        chunk=chunk,
                        retrieval_score=0.9,
                        retriever_version=retriever_version,
                        index_snapshot_ref=self.index_snapshot_ref,
                        retrieved_at=retrieved_at,
                    )
                )

        return candidates

    def text_for_ref(self, text_ref: str) -> str | None:
        """Return controlled fixture text for an authorized text ref."""

        return self._text_by_ref.get(text_ref)

    @staticmethod
    def _text_ref(document_id: str) -> str:
        return f"txt://{document_id}"
