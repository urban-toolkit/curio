import streamlit as st

from langchain_community.document_loaders import SeleniumURLLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_ollama import OllamaEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM

template = """
You are an assistant for question-answering tasks. Use the following pieces of retrieved context to answer the question. If you dont know the answer, just say that you don't know. Use three sentences maximum and keep the answer concise.
Question: {question}
Context: {context}
Answer:
"""
embeddings = OllamaEmbeddings(model="llama3.2")
vector_store = InMemoryVectorStore(embeddings)

model = OllamaLLM(model="llama3.2")

def load_page(url):
	loader = SeleniumURLLoader(
		urls=[url]
	)
	documents = loader.load()
	return documents

def split_text(documents):
	text_splitter = RecursiveCharacterTextSplitter(
		chunk_size=1000,
		chunk_overlap=200,
		add_start_index=True

	)
	data = text_splitter.split_documents
	return data

def index_docs(documents):
	vector_store.add_documents(documents)

def retrieve_docs(query):
	return vector_store.similarity_search(query)

def answer_question(question, context):
	prompt = ChatPromptTemplate.from_template(template)
	chain = prompt | model
	chain.invoke({"question": question, "context": context})

st.title("AI Crawler")
url = st.text_input("Enter URL:")

# documents = load_page(url)
# chunked_documents = split_text(documents)

# index_docs(chunked_documents)

# question = st.chat_input()
# if question:
	