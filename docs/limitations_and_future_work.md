# Limitations and Future Work

The current Authoritative Architecture Decision Resolver is built as a robust v1 prototype to prove the core governance model. Below are three key technical limitations of the current implementation and the roadmap for addressing them in v2, ensuring the core authority resolver logic remains untouched.

## 1. Local TF-IDF vs. Dense Embeddings

**Limitation:** 
The system currently uses Scikit-Learn's TF-IDF vectorizer and cosine similarity for document retrieval. While this allows the prototype to run fully offline without external dependencies, it relies on exact keyword matching. It struggles with semantic variations (e.g., matching "database" with "datastore") and is sensitive to tokenization quirks (like stripping numeric variants).

**Future Work (v2):** 
The retrieval layer (`retrieval.py`) will be swapped to use dense vector embeddings (e.g., via OpenAI's `text-embedding-3-small` or a local HuggingFace model) backed by a vector database like ChromaDB or FAISS. Because the retrieval layer is explicitly decoupled from the authority scoring layer (`authority.py`), this upgrade will purely improve candidate selection relevance without altering any governance rules.

## 2. SQLite vs. PostgreSQL

**Limitation:** 
The application relies on a local SQLite file (`adr.db`). While performant for small-to-medium teams, SQLite lacks native support for horizontal scaling, advanced JSON querying, and high-concurrency writes, making it unsuitable for a global enterprise deployment.

**Future Work (v2):** 
The database layer (`database.py`) is written in strict ANSI SQL (with the exception of `AUTOINCREMENT`). In v2, the connection logic will be swapped to use a PostgreSQL adapter (e.g., `asyncpg` or `psycopg2`). The `AUTOINCREMENT` fields will map seamlessly to PostgreSQL `SERIAL` or `IDENTITY` columns. The underlying schemas, access rules, and audit logging table structures will remain identical.

## 3. Mock LLM vs. Real Provider Endpoint

**Limitation:** 
Currently, if no API key is provided, the system falls back to an in-memory, deterministic Mock LLM (`ai.py`). This mock provider relies on basic sentence overlap to extract answers and citations. It cannot synthesize complex summaries, reason across multiple document sections, or handle highly nuanced user queries.

**Future Work (v2):** 
The system will be fully integrated with a production-grade LLM provider (e.g., Google Gemini, OpenAI GPT-4, or Anthropic Claude) via standard API clients. The strict prompt boundaries—which enforce that the LLM only receives the single authoritative document chosen by the resolver and neutralizes embedded instructions—are already in place. The transition to a real LLM will simply improve the fluency and reasoning of the final generated response.
