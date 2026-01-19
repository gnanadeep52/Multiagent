# Autonomous Research & Writing Orchestrator

This project implements an AI-driven research and writing pipeline that automatically answers user questions in a structured, reliable, and step-by-step way.

Instead of using one AI to do everything, the system divides work into clear phases and roles, ensuring better control, safety, and output quality.


# What problem this solves

When using a single AI call:

- Research can be incomplete

- Writing can be unstructured

- Answers may loop or fail silently

- File handling is unsafe or inconsistent

This system solves those problems by:

- Separating research and writing

- Assigning specialized agents to each task

- Using supervisors to control flow

- Safely reading, writing, and editing files

- Preventing infinite AI loops

# How it works 

1. User asks a question

2. Research phase

   - One agent searches the web

   - Another agent reads relevant webpages

   - A supervisor decides when research is sufficient

3. Writing phase

   - A note-taker agent creates an outline

   - A document writer agent produces the final answer

   - Output is saved to files

4. Completion

   - The system stops automatically

   - The final answer is printed

   - Generated files are listed


# Agents and their roles

- Search Agent

Finds relevant information using web search.

- Web Scraper Agent

Reads and extracts content from web pages.

- Note Taker Agent

Creates a structured outline before writing.

- Document Writer Agent

Writes the final answer based on the outline and research.


# Supervisors

 - Team Supervisors

   1. Decide which agent should act next

   2. Prevent unnecessary repetition

   3. Stop when work is complete

- Top-Level Supervisor

   1. Ensures research happens before writing

   2. Controls the overall execution order

# Safety and reliability

- Prevents infinite loops using execution limits

- Ensures files are written with safe filenames

- Separates planning from writing to avoid messy output

- Uses deterministic flow for predictable results

# Output

outline.txt – structured outline of the answer

answer.txt – final written response

Both files are saved in the temp/ directory.


## Flowchart

```mermaid
flowchart TD
    START([User Question]) --> TOP_SUPERVISOR

    TOP_SUPERVISOR{Top Supervisor}
    TOP_SUPERVISOR -->|research_done = false| RESEARCH_TEAM
    TOP_SUPERVISOR -->|research_done = true and writing_done = false| WRITING_TEAM
    TOP_SUPERVISOR -->|research_done = true and writing_done = true| END([END])

    subgraph RESEARCH_TEAM["Research Team"]
        RSUP{Research Supervisor}
        SEARCH_AGENT["Search Agent (TavilySearch)"]
        WEB_SCRAPPER["Web Scrapper Agent (scrape_webpages)"]
        RSUP --> SEARCH_AGENT
        RSUP --> WEB_SCRAPPER
        SEARCH_AGENT --> RSUP
        WEB_SCRAPPER --> RSUP
    end

    RESEARCH_TEAM --> TOP_SUPERVISOR

    subgraph WRITING_TEAM["Writing Team"]
        WSUP{Writing Supervisor}
        NOTE_TAKER["Note Taker Agent (create_outline)"]
        DOC_WRITER["Doc Writer Agent (read_document, write_document, edit_document)"]
        WSUP --> NOTE_TAKER
        WSUP --> DOC_WRITER
        NOTE_TAKER --> WSUP
        DOC_WRITER --> WSUP
    end

    WRITING_TEAM --> TOP_SUPERVISOR
  ```


  References:

  https://docs.langchain.com/oss/python/langgraph/overview
  
  https://docs.langchain.com/oss/python/langchain/multi-agent/index?search=agent