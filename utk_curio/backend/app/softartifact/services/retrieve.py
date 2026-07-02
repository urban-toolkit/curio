from __future__ import annotations
from .ingest import softartifacts_root
import nltk # natural language processing
nltk.download('punkt')
from nltk.tokenize import word_tokenize 
import json

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
 
#to tokenize the query
def _tokenize(query):
    return word_tokenize(query.lower())

