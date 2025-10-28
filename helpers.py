import os
import re
import json
import sqlite3
import unicodedata
import time, random
import numpy as np

from flask import redirect, session, g, current_app
from functools import wraps
from google import genai
from google.genai import types
from sklearn.metrics.pairwise import cosine_similarity

from dotenv import load_dotenv
load_dotenv()  # Always load first

# Initialize Client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Cache to minimize Gemini api calls
CACHE_FILE = "embedding_cache.json"

# Load cache from file if exists
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        embedding_cache = json.load(f)
else:
    embedding_cache = {}


def save_cache():
    """Save the embedding cache to file."""

    with open(CACHE_FILE, "w") as f:
        json.dump(embedding_cache, f, indent=4)  # Pretty print


# https://flask.palletsprojects.com/en/latest/patterns/viewdecorators/
def login_required(f):
    """Decorate routes to require login."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


# https://flask.palletsprojects.com/en/latest/patterns/sqlite3/
def get_db():
    """Store db connection for current request in Flask's g"""

    # Creat connection if none
    if "db" not in g:
        db_path = os.path.join(current_app.root_path, "technus.db")
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row  # Enable access via column names like CS50 SQL
    return g.db


def close_db(error=None):
    """Close the DB connection at the end"""

    # Remove db connection from g if any
    db = g.pop("db", None)
    # Close the connection if any (to free resources)
    if db is not None:
        db.close()


def db_teardown(app):
    """Register database teardown for the given Flask app."""

    app.teardown_appcontext(close_db)


def normalize_text(text):
    """Normalize string: lowercase, remove punctuation, collapse spaces."""

    # Ensure string input
    if not isinstance(text, str):
        return ""

    text = unicodedata.normalize("NFKD", text)  # Normalize fancy unicode
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)  # Remove punctuation (non-word, non-space)
    text = re.sub(r"\s+", " ", text)      # Collapse multiple spaces
    return text.strip()                   # Remove leading/trailing spaces and return


def get_embedding(words: list[str]) -> np.ndarray | None:
    """Return embedding vectors for a word list with persistent caching (with batching + rate limiting)"""

    all_emb = []  # Returned at the end
    uncached = []

    # Prepare the return list
    for w in words:
        # Add embedding vectors if word is cached
        if w in embedding_cache:
            all_emb.append(np.array(embedding_cache[w]))
        # Reserve index and mark as uncached
        else:
            all_emb.append(None)
            uncached.append(w)

    if uncached:
        BATCH_SIZE = 80
        try:
            for start_index in range(0, len(uncached), BATCH_SIZE):
                # Batch article keywords to avoid hitting quota
                batch = uncached[start_index:(start_index + BATCH_SIZE)]         
                try:
                    # Embed this batch
                    result = [
                        np.array(e.values) for e in client.models.embed_content(
                            model="gemini-embedding-001",
                            contents=batch,
                            config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=768)
                        ).embeddings
                    ]
                except Exception as e:
                    # Handle possible rate limit or network errors
                    print(f"[Rate-limit or network error] Retrying in 15s: {e}")
                    time.sleep(15)
                    # Retry this batch
                    result = [
                        np.array(e.values) for e in client.models.embed_content(
                            model="gemini-embedding-001",
                            contents=batch,
                            config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=768)
                        ).embeddings
                    ]

                # Normalize embeddings
                result = np.array(result, dtype=float)
                result = result / np.linalg.norm(result, axis=1, keepdims=True)  # Normalize

                # Fill reserved and update cache
                r_index = 0
                for i, emb in enumerate(all_emb):
                    if emb is None:
                        all_emb[i] = result[r_index]                                   # Assign to reserved spot
                        embedding_cache[uncached[r_index]] = result[r_index].tolist()  # Update cache => { uncached word: result }
                        r_index += 1                                                   # Iterate through result

                save_cache()
                # Regulate requests slightly (random delay)
                time.sleep(random.uniform(1.5, 3.0))
        
        except Exception as e:
            print(f"[Embedding error] text='{words[:50]}…': {e}")
            # Return from cached if any. Otherwise, none
            all_emb = [e for e in all_emb if e is not None]
            if not all_emb:
                return None
            
    return np.array(all_emb)
    

def get_sematic_matches(user_kw: list[str], article_kw: list[str], threshold: float = 0.92) -> list[str]:
    """Return user keywords that semantically match any article keyword."""

    # Skip early if no inputs
    if not user_kw or not article_kw:
        return []
    
    emb_matrix1 = get_embedding(user_kw)
    emb_matrix2 = get_embedding(article_kw)

    # Validate vector lists
    if emb_matrix1 is None or emb_matrix2 is None:
        return []
    
    # Compute similarity
    similarity_matrix = cosine_similarity(emb_matrix1, emb_matrix2)

    # Keep user keywords that have at least one match above threshold
    matched = [
        user_kw[i]
        for i in range(len(user_kw))
        if np.any(similarity_matrix[i] >= threshold)
    ]

    return matched