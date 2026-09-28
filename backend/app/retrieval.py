"""
Lightweight local retrieval. Uses TF-IDF cosine similarity as a practical
stand-in for embeddings/vector search so the prototype runs fully offline
with no external API keys. Swappable for FAISS/Chroma + real embeddings
by replacing `_vectorizer`/`_matrix` with an embedding index — the public
`search()` interface would stay identical.

IMPORTANT: retrieval only determines RELEVANCE (candidate documents).
It never decides authority/trust — that is authority.py's job.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .database import get_conn

_vectorizer = None
_matrix = None
_doc_ids = []


def build_index():
    global _vectorizer, _matrix, _doc_ids
    conn = get_conn()
    rows = conn.execute(
        """SELECT d.id as document_id, d.title, GROUP_CONCAT(v.content, ' ') as content
           FROM documents d LEFT JOIN versions v ON v.document_id = d.id
           GROUP BY d.id"""
    ).fetchall()
    _doc_ids = [r["document_id"] for r in rows]
    corpus = [(r["title"] or "") + " " + (r["content"] or "") for r in rows]
    if not corpus:
        _vectorizer, _matrix = None, None
        return
    _vectorizer = TfidfVectorizer(stop_words="english", max_features=20000)
    _matrix = _vectorizer.fit_transform(corpus)


def search(query, top_k=5):
    global _vectorizer, _matrix, _doc_ids
    if _vectorizer is None:
        build_index()
    if _vectorizer is None or _matrix is None or _matrix.shape[0] == 0:
        return []
    qvec = _vectorizer.transform([query])
    sims = cosine_similarity(qvec, _matrix)[0]
    ranked = sorted(zip(_doc_ids, sims), key=lambda t: t[1], reverse=True)
    return [{"document_id": doc_id, "relevance": float(score)} for doc_id, score in ranked[:top_k] if score > 0]
