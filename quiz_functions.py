# quiz_functions.py
from langchain_core.runnables import RunnablePassthrough, RunnableSequence
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain_qdrant import QdrantVectorStore, RetrievalMode,FastEmbedSparse
from langchain_community.document_compressors import JinaRerank
from langchain.retrievers import ContextualCompressionRetriever
from qdrant_client import QdrantClient
from typing import List
import os
import requests
from langchain_core.embeddings import Embeddings

# Initialize LLM
os.environ["DEEPSEEK_API_KEY"] = "API KEY"
os.environ["JINA_API_KEY"] = "API KEY"
llm = ChatDeepSeek(model="deepseek-chat", temperature=0)

# Qdrant Client Configuration
def initialize_qdrant_client():
    return QdrantClient(
        url="Qdrant URL",
        api_key="API KEY",
        timeout=100
    )

# Custom Jina Embeddings
class JinaAPIEmbeddings(Embeddings):
    """Custom LangChain embeddings using Jina API."""
    
    def __init__(self, api_key: str = os.getenv("JINA_API_KEY"), model: str = "jina-embeddings-v3", 
                 dimensions: int = 1024, task: str = "retrieval.query"):
        self.api_key = api_key or "API KEY"
        self.model = model
        self.dimensions = dimensions
        self.task = task
        self.api_url = "https://api.jina.ai/v1/embeddings"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        data = {
            "model": self.model,
            "task": self.task,
            "late_chunking": True,
            "dimensions": self.dimensions,
            "embedding_type": "float",
            "input": [{"text": text} for text in texts],
        }
        response = requests.post(self.api_url, headers=self.headers, json=data)
        response.raise_for_status()
        return [item["embedding"] for item in response.json()["data"]]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._get_embeddings(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._get_embeddings([text])[0]

# Initialize embeddings and vector store
jina_embeddings = JinaAPIEmbeddings()
qdrant_client = initialize_qdrant_client()
splade_embeddings = FastEmbedSparse(model_name="prithivida/Splade_PP_en_v1")
def initialize_vector_store(collection_name: str = "Books4CollabEdu"):
    return QdrantVectorStore(
    client=qdrant_client,
    collection_name="Books4CollabEdu",
    embedding=jina_embeddings,
    sparse_embedding=splade_embeddings,
    retrieval_mode=RetrievalMode.HYBRID,
    vector_name="jina",
    sparse_vector_name="splade_sparse",

)


# Initialize retriever components
vector_store = initialize_vector_store()
base_retriever = vector_store.as_retriever(search_kwargs={"k": 40})
jina_reranker = JinaRerank(model="jina-reranker-v2-base-multilingual", top_n=1)
compression_retrieverv2 = ContextualCompressionRetriever(
    base_compressor=jina_reranker,
    base_retriever=base_retriever
)

# Define prompts
system_message = """You are an AI assistant specialized in systematically creating high-quality quizzes through a structured five-step process.
    Your role involves the following sequential tasks:
    1. **Quiz Metadata Extraction**: Determine quiz scope, question count, and key technical topics.
    2. **Textbook Context Retrieval**: Identify clear explanations, definitions, formulas, and comparisons from textbooks.
    3. **MCQ Generation**: Craft multiple-choice questions with precise technical wording, varied types, and difficulty levels.
    4. **Distractor Generation**: Develop plausible incorrect answers reflecting common student errors.
    5. **CSV Validation**: Structure and validate quiz questions and answers into a formatted CSV."""

quiz_metadata_prompt = """Role: Detailed Content Generator
    Your task is to analyze the quiz description provided and generate:
    - Total number of questions needed (only the number)
    - Technical areas covered (list exactly 2-3 key concepts)
    - Output should have no preambles, formatting, Escape sequences(like new lines) or decorators

    Quiz Description:
    {quiz_description}

    Structured Output:
    [Number of questions]
    [Technical topics (python list of strings)]
    """

question_expansion_prompt = """
Role: Question Expansion Generator

Your task is to create high-quality targeted questions for textbook context retrieval, using the following technical topics:
{topics}

Instructions:
1. For each topic, generate 2-4 retrieval-style questions that:
   - Clearly ask for core **definitions**, **principles**, or **terminology**
   - Identify **key rules**, **equations**, or **operational logic**
   - Compare the topic with closely related concepts or alternatives
   - Target common **misconceptions**, **confusions**, or **edge cases**

2. Keep the questions:
   - Concise and technically accurate
   - Appropriate for an undergraduate-level computer engineering curriculum
   - Diverse in structure (what/how/why/compare/define)

3. DO NOT include any extra explanation, headers, or markdown.

Structured Output:
Return a clean **raw Python list of strings(No "\\n")** with just the questions (no preambles, formatting, Escape sequences(like new lines) or decorators) minimum {number}.

Example Format:
["What is the purpose of the OSI model in network design?","How does the TCP/IP model differ from the OSI model?","What is subnetting and why is it used in IP addressing?","Compare IPv4 and IPv6 in terms of address structure and size."]
"""

combined_mcq_prompt = HumanMessagePromptTemplate.from_template(
    r"""Role: Computer Engineering MCQ Generator (Theory + Code)

Generate {Number} MCQs on {topics} with {context} following these specifications:

◆ MATHEMATICAL NOTATION REQUIREMENTS:
- All equations MUST use LaTeX formatting between $ symbols
- Escape curly braces in exponents/subscripts: $n^{{\log_2 2}}$
- Example formats:
  - Time complexity: $O(n^2)$, $O(2^n)$, $O(\log n)$
  - Equations: $\sum_{{i=1}}^n i^2$, $\int_a^b f(x)dx$
  - Greek letters: $\alpha$, $\beta$, $\gamma$

◆ QUESTION TYPES & DISTRIBUTION:
1. Calculation Problems (20-30%) - Must include LaTeX equations
2. Code Analysis (30-40%) - Use executable code snippets
3. Practical Scenarios (30-50%) - Real engineering applications

◆ EXAMPLE QUESTION FORMAT:
MCQ 1:
Type: calculation
Difficulty: 4/5
Context: Algorithm complexity analysis
Question: What is the solution to $T(n) = 2T(n/2) + n$?
A) $O(n)$ (missing log factor)
B) $O(n^2)$ (overestimation)
C) $O(n\log n)$ [Correct]
D) $O(2^n)$ (exponential overestimation)
Correct: C) [Master Theorem Case 2: $n^{{\log_2 2}} = n$ vs $f(n)=n$]

◆ CODE EXAMPLE:
Type: code analysis
Difficulty: 3 (pointer arithmetic application)
Context: Embedded systems memory access
Question: Given:
C Programmig
int arr[5] = {{1,2,3,4,5}};
int* ptr = arr + 3;
What is the value of *(ptr - 1)?
A) 1 (incorrect array start)
B) 2 [Correct]
C) 3 (wrong offset calculation)
D) Segmentation fault (invalid memory assumption)
Correct: B) [Pointer arithmetic accounts for element size]

VALIDATION CHECKS:
- Reject any question missing $ delimiters
- Verify LaTeX renders correctly
- Confirm code examples execute as described"""
)

csv_validation_prompt = HumanMessagePromptTemplate.from_template(
r"""Role: CSV Validation Specialist

Validate and format MCQs into CSV with strict LaTeX enforcement:

CSV COLUMNS:
ID,Question,Type,Answer,Distractor1,Distractor2,Distractor3,Difficulty,Topics,Source,LaTeX_Valid

VALIDATION RULES:
1. LaTeX Requirements:
   - All equations must be $delimited$
   - Use double curly braces for exponents: $\sum_{{i=1}}^n$
   - Column LaTeX_Valid must be "TRUE" or "FALSE"

2. Example Valid Row:
1,"Solve $\int_0^1 x^2 dx$","Calculation","$\frac{{1}}{{3}}$","1","$\frac{{1}}{{2}}$","$\frac{{1}}{{4}}$",3,"Calculus","Textbook Ch2","TRUE"

3. Quality Checks:
- Difficulty matches complexity (1-5 scale)
- Each distractor shows distinct error pattern
- Sources are verifiable

4. Rejection Criteria:
- Missing $ delimiters
- Invalid LaTeX syntax
- Untraceable sources
- Duplicate questions"""
)

# Create prompt templates
quiz_metadata_template = ChatPromptTemplate.from_messages([
    ("system", system_message),
    ("human", quiz_metadata_prompt)
])

question_expansion_template = ChatPromptTemplate.from_messages([
    ("system", system_message),
    ("human", question_expansion_prompt)
])

# Create chains
quiz_metadata_chain = quiz_metadata_template | llm | StrOutputParser()
question_expansion_chain = question_expansion_template | llm | StrOutputParser()

# Define retrieval chain
chat_prompt = ChatPromptTemplate.from_messages([
    system_message,
    combined_mcq_prompt,
    csv_validation_prompt
])

retrieval_chain = (
    {
        "context": RunnablePassthrough(),
        "topics": RunnablePassthrough(),
        "Number": RunnablePassthrough(),
    }
    | RunnablePassthrough().assign(
        response=(
            chat_prompt
            | llm
            | StrOutputParser()
        )
    )
)