from __future__ import annotations
from .ingest import softartifacts_root
import json
import nltk # natural language processing
from nltk.tokenize import word_tokenize 
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt_tab')

#load json chunk accorind to artifactId
#return an array of dictionary accroding to the json
def _load_chunk(artifactId):
    chunkPath = softartifacts_root() / artifactId / "chunk.json"
    if not chunkPath.is_file():
        return None 

    #reading json file and return the array
    try:
        with open(chunkPath, 'r') as f:
            data = json.load(f);
    except:
        return None
    
    return data
 

#to tokenize the query and text
def _tokenize(text):
    return word_tokenize(text.lower())


#scoring each chunk depends on the query
#using TF_IDF and cosine similarity to score query to text chunk
def search_chunks(query, artifactId, top_k = 5):
    chunks = _load_chunk(artifactId)
    tokenized_query = _tokenize(query)

    texts = [chunk.get("text","") for chunk in chunks]

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

    results = [
        {**text, "score": float(score)}
        for text, score in ranked
        if score > 0
    ][:top_k]
    return results