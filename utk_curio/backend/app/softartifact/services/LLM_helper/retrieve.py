from __future__ import annotations
from ..ingest import softartifacts_root
from .store import list_chunks
import nltk # natural language processing
from nltk.tokenize import word_tokenize 
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt_tab')

#load json chunk accorind to artifact_id
#return an array of dictionary accroding to the json
def _load_chunk(artifactId):
    chunks = list_chunks(artifactId)
    return chunks or None   # search_chunks already treats falsy as []
 

#to tokenize the query and text
def _tokenize(text):
    return word_tokenize(text.lower())


#scoring each chunk depends on the query
#using TF_IDF and cosine similarity to score query to text chunk
def search_chunks(query, artifact_id, top_k = 8):
    if top_k is None:
        top_k = 8

    #from artifact_id return the chunk that is stored in .curio 
    chunks = _load_chunk(artifact_id)
    if not chunks:
        return []

    texts = [chunk.get("text","") for chunk in chunks]
    if not any(texts):
        return []

    vectorizer = TfidfVectorizer(tokenizer = _tokenize, lowercase = False)
    chunk_vectors = vectorizer.fit_transform(texts)
    query_vector = vectorizer.transform([query])

    scores = cosine_similarity(query_vector, chunk_vectors).flatten()
    
    #sorting , return an array
    ranked = sorted(
        zip(chunks, scores),
        key = lambda pair: pair[1],
        reverse = True
    )

    results = []
    for chunk, score in ranked:
        if score <= 0:
            continue
        results.append({**chunk, "score": float(score)})
        if len(results) >= top_k:
            break
    return results