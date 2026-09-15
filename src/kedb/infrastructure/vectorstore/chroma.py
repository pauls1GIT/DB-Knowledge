from __future__ import annotations
import chromadb
from uuid import UUID
from kedb.config import settings
from kedb.domain.entities import ArticleChunk, RetrievalCandidate


class ChromaVectorStore:
    def __init__(self, path=None, collection_name="approved_kedb"):
        self.client=chromadb.PersistentClient(path=path or settings.chroma_path)
        self.collection=self.client.get_or_create_collection(collection_name, metadata={"hnsw:space":"cosine"})
    def upsert(self, chunks, vectors, metadata):
        self.collection.upsert(ids=[str(c.id) for c in chunks], embeddings=vectors, documents=[c.content for c in chunks], metadatas=metadata)
    def search(self, vector, limit=10):
        if self.collection.count()==0: return []
        out=self.collection.query(query_embeddings=[vector], n_results=min(limit,self.collection.count()), include=["metadatas","distances"])
        results=[]
        for md,dist in zip(out["metadatas"][0], out["distances"][0]):
            results.append(RetrievalCandidate(known_error_id=UUID(md["known_error_id"]), article_version_id=UUID(md["article_version_id"]), title=md["title"], vector_score=max(0.0,1.0-float(dist))))
        return results
