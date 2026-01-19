import os
import re
from typing import Annotated, Literal, Optional, List, Dict, Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from langchain_community.document_loaders import WebBaseLoader
from langgraph.graph import StateGraph, START
from langgraph.graph.message import MessagesState
from langgraph.types import Command
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

# Environment & Storage

load_dotenv()

TEMP_DIR = os.path.join(os.getcwd(), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


def safe_filename(name: str) -> str:
    """Sanitize a filename to be filesystem-safe."""
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name or "document.txt")


# Tools

@tool
def scrape_webpages(urls: List[str]) -> str:
    """
    Fetch and extract text from a list of webpages.

    Args:
        urls: List of webpage URLs.

    Returns:
        Combined text content from all pages.
    """
    loader = WebBaseLoader(urls)
    docs = loader.load()
    return "\n\n".join(doc.page_content for doc in docs)


@tool
def create_outline(
    points: Annotated[List[str], "List of outline section points"],
    file_name: Annotated[str, "Outline filename"] = "outline.txt",
) -> str:
    """
    Create a structured outline and save it to a file.

    Args:
        points: Section headings or bullets.
        file_name: Output file name (saved under temp/).

    Returns:
        Confirmation message.
    """
    file_name = safe_filename(file_name)
    path = os.path.join(TEMP_DIR, file_name)

    with open(path, "w", encoding="utf-8") as f:
        for i, p in enumerate(points, 1):
            f.write(f"{i}. {p}\n")

    return f"Outline saved to {file_name}"


@tool
def write_document(
    file_name: Annotated[str, "Document filename"] = "document.txt",
    content: Annotated[str, "Document content"] = "",
) -> str:
    """
    Write text content to a document (overwrite).

    Args:
        file_name: Document name (saved under temp/).
        content: Text content.

    Returns:
        Confirmation message.
    """
    file_name = safe_filename(file_name)
    path = os.path.join(TEMP_DIR, file_name)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return f"Document written to {file_name}"


@tool
def read_document(
    file_name: Annotated[str, "Document filename"],
) -> str:
    """
    Read a document from the temp directory.

    Args:
        file_name: Document name.

    Returns:
        Document contents or error message.
    """
    file_name = safe_filename(file_name)
    path = os.path.join(TEMP_DIR, file_name)

    if not os.path.exists(path):
        return "Document not found."

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@tool
def edit_document(
    file_name: Annotated[str, "Document filename"],
    inserts: Annotated[Dict[int, str], "Line-numbered inserts"],
) -> str:
    """
    Insert text into a document at specific line numbers.

    Args:
        file_name: Document name.
        inserts: Mapping of 1-indexed line numbers to text inserts.

    Returns:
        Confirmation message.
    """
    file_name = safe_filename(file_name)
    path = os.path.join(TEMP_DIR, file_name)

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("")

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line_no, text in sorted(inserts.items()):
        if not text.endswith("\n"):
            text += "\n"
        idx = min(max(line_no - 1, 0), len(lines))
        lines.insert(idx, text)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return f"Document edited and saved to {file_name}"



# State
class State(MessagesState):
    """
    Shared state across the entire graph.
    """
    next: str
    doc_name: Optional[str]
    outline_name: Optional[str]
    sources: List[str]
    artifacts: Dict[str, Any]
    research_done: bool
    writing_done: bool



# LLM

openai_key = os.getenv("OPENAI_API_KEY")
if not openai_key:
    raise RuntimeError("OPENAI_API_KEY missing")

llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    api_key=openai_key,
)

search_tool = TavilySearch(max_results=3)


# Supervisors

def make_team_supervisor(llm, members: List[str], max_turns: int = 10):
    """
    LLM-driven supervisor that routes among workers until FINISH.
    """
    options = ["FINISH"] + members

    class Router(BaseModel):
        next: Literal[tuple(options)]  # type: ignore

    system_prompt = (
        "You are a supervisor tasked with managing a conversation between the "
        f"following workers: {members}. Given the user's request and the conversation so far, "
        "respond with the worker to act next. Each worker will perform a task and respond with "
        "their results. When a useful result for the team's purpose has been produced, "
        "respond with FINISH. Return ONLY one of: "
        f"{options}"
    )

    def supervisor(state: State):
        # Safety cap to avoid runaway loops
        if len(state["messages"]) >= max_turns:
            return Command(goto="__end__")

        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        decision = llm.with_structured_output(Router).invoke(messages)

        if decision.next == "FINISH":
            return Command(goto="__end__")

        return Command(goto=decision.next)

    return supervisor



# Research team agents

search_agent = create_react_agent(
    llm,
    tools=[search_tool],
    prompt=(
        "You are the SEARCH agent in a research team. "
        "Your job is to use web search to gather useful, relevant facts for the user's question. "
        "If the query is broad, make reasonable assumptions and proceed. "
        "Do NOT ask the user for clarification. "
        "Return a concise set of findings and (when available) URLs to consult."
    ),
)

def search_node(state: State):
    r = search_agent.invoke(state)
    return Command(
        update={"messages": [HumanMessage(content=r["messages"][-1].content, name="search")]},
        goto="supervisor",
    )


web_scrapper_agent = create_react_agent(
    llm,
    tools=[scrape_webpages],
    prompt=(
        "You are the WEB_SCRAPPER agent. "
        "Given one or more URLs, scrape and return the most relevant textual content for answering the user's question. "
        "Do NOT ask the user for clarification."
    ),
)

def web_scrapper_node(state: State):
    r = web_scrapper_agent.invoke(state)
    return Command(
        update={"messages": [HumanMessage(content=r["messages"][-1].content, name="web_scrapper")]},
        goto="supervisor",
    )

# Research Graph (search + web_scrapper)
research_supervisor = make_team_supervisor(llm, ["search", "web_scrapper"], max_turns=10)

research_graph = StateGraph(State)
research_graph.add_node("supervisor", research_supervisor)
research_graph.add_node("search", search_node)
research_graph.add_node("web_scrapper", web_scrapper_node)
research_graph.add_edge(START, "supervisor")
research_graph = research_graph.compile()


# Writing team agents
note_taker_agent = create_react_agent(
    llm,
    tools=[create_outline],
    prompt=(
        "You are the NOTE_TAKER agent. "
        "Create a clear outline that will structure the final answer to the user's question. "
        "Keep it short and logical (typically 5-10 points). "
        "Save the outline using create_outline to the provided outline filename if available."
    ),
)


def note_taker_node(state: State):
    # Ensure outline_name exists
    outline_name = state.get("outline_name") or "outline.txt"
    
    state_with_hint = dict(state)
    state_with_hint["messages"] = state["messages"] + [
        HumanMessage(content=f"(system hint) Save outline to file: {outline_name}")
    ]
    r = note_taker_agent.invoke(state_with_hint)

    return Command(
        update={"messages": [HumanMessage(content=r["messages"][-1].content, name="note_taker")]},
        goto="supervisor",
    )



doc_writer_agent = create_react_agent(
    llm,
    tools=[read_document, write_document, edit_document],
    prompt=(
        "You are the DOC_WRITER agent.\n\n"
        "You MUST produce the final answer in EXACTLY this format:\n"
        "SECTION 1: OUTLINE\n"
        "- Include the outline points (verbatim) from the outline document.\n\n"
        "SECTION 2: SUMMARY\n"
        "- Write a clear summary explaining each outline point in order.\n"
        "\n"
        "IMPORTANT:\n"
        "- Always read the outline document before writing.\n"
        "- Save the complete output to the document filename provided in state (doc_name) if available.\n"
        "- Do NOT ask the user for clarification.\n"
    ),
)


def doc_writer_node(state: State):
    # Ensure doc_name exists
    doc_name = state.get("doc_name") or "answer.txt"
    outline_name = state.get("outline_name") or "outline.txt"

    # Provide explicit filenames as a hint message
    state_with_hint = dict(state)
    state_with_hint["messages"] = state["messages"] + [
        HumanMessage(content=f"(system hint) Outline file: {outline_name}. Final doc file: {doc_name}.")
    ]

    r = doc_writer_agent.invoke(state_with_hint)
    return Command(
        update={"messages": [HumanMessage(content=r["messages"][-1].content, name="final")]},
        goto="supervisor",
    )



# Writing Graph (note_taker + doc_writer)

writing_supervisor = make_team_supervisor(llm, ["note_taker", "doc_writer"], max_turns=10)

writing_graph = StateGraph(State)
writing_graph.add_node("supervisor", writing_supervisor)
writing_graph.add_node("note_taker", note_taker_node)
writing_graph.add_node("doc_writer", doc_writer_node)
writing_graph.add_edge(START, "supervisor")
writing_graph = writing_graph.compile()



# Top-Level Supervisor


def top_supervisor(state: State):
    if not state.get("research_done", False):
        return Command(goto="research_team")

    if not state.get("writing_done", False):
        return Command(goto="writing_team")

    return Command(goto="__end__")


def run_research(state: State):
    out = research_graph.invoke(state)
    return Command(
        update={"messages": out["messages"], "research_done": True},
        goto="top_supervisor",
    )


def run_writing(state: State):
    out = writing_graph.invoke(state)
    return Command(
        update={"messages": out["messages"], "writing_done": True},
        goto="top_supervisor",
    )


# Top-Level Graph

graph = StateGraph(State)
graph.add_node("top_supervisor", top_supervisor)
graph.add_node("research_team", run_research)
graph.add_node("writing_team", run_writing)
graph.add_edge(START, "top_supervisor")
graph = graph.compile()



# Run
question = input("Ask any question: ").strip()

initial_state: State = {
    "messages": [HumanMessage(content=question)],
    "next": "",
    "doc_name": "answer.txt",
    "outline_name": "outline.txt",
    "sources": [],
    "artifacts": {},
    "research_done": False,
    "writing_done": False,
}

result = graph.invoke(initial_state)

print("\n=== FINAL ANSWER ===\n")

final_answer = None
for m in result["messages"]:
    if getattr(m, "name", None) == "final":
        final_answer = m.content

print(final_answer or (result["messages"][-1].content if result["messages"] else ""))
print("\nFiles in temp/:", os.listdir(TEMP_DIR))
