import operator
from typing import Annotated
from typing_extensions import TypedDict

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from langchain_community.document_loaders import WikipediaLoader
from langchain_community.tools.tavily_search import TavilySearchResults

from langchain_ollama import ChatOllama

from langgraph.graph import StateGraph, START, END

# Default ctx size of 2048 for Ollama will cut off context and not let the llm answer. Particularly
# if you get a response asking you for the question, the context got cut off.
CONTEXT_SIZE = 32768
llm = ChatOllama(
    model="qwen2.5",
    temperature=0,
    base_url="http://host.docker.internal:11434",
    num_ctx=CONTEXT_SIZE,
)


class State(TypedDict):
    question: str
    answer: str
    context: Annotated[list, operator.add]


def search_web(state):
    """Retrieve docs from web search"""

    # Search
    tavily_search = TavilySearchResults(max_results=3)
    search_docs = tavily_search.invoke(state["question"])

    # Format
    formatted_search_docs = "\n\n---\n\n".join(
        [
            f'<Document href="{doc["url"]}"/>\n{doc["content"]}\n</Document>'
            for doc in search_docs
        ]
    )

    return {"context": [formatted_search_docs]}


def search_wikipedia(state):
    """Retrieve docs from wikipedia"""

    # Search
    search_docs = WikipediaLoader(query=state["question"], load_max_docs=2).load()

    # Format
    formatted_search_docs = "\n\n---\n\n".join(
        [
            f'<Document source="{doc.metadata["source"]}" page="{doc.metadata.get("page", "")}"/>\n{doc.page_content}\n</Document>'
            for doc in search_docs
        ]
    )

    return {"context": [formatted_search_docs]}


def generate_answer(state):
    """Node to answer a question"""

    # Get state
    context = state["context"]
    question = state["question"]

    # Template
    answer_template = """Answer the question {question} using this context: {context}"""
    answer_instructions = answer_template.format(question=question, context=context)

    # Answer
    answer = llm.invoke(
        [SystemMessage(content=answer_instructions)]
        + [HumanMessage(content=f"Answer the question.")]
    )

    # Append it to state
    return {"answer": answer}


# Add nodes
builder = StateGraph(State)

# Initialize each node with node_secret
builder.add_node("search_web", search_web)
builder.add_node("search_wikipedia", search_wikipedia)
builder.add_node("generate_answer", generate_answer)

# Flow
builder.add_edge(START, "search_wikipedia")
builder.add_edge(START, "search_web")
builder.add_edge("search_wikipedia", "generate_answer")
builder.add_edge("search_web", "generate_answer")
builder.add_edge("generate_answer", END)
graph = builder.compile()
