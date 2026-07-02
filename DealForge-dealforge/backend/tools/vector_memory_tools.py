# backend/tools/vector_memory_tools.py

import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from langsmith import traceable

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

from db.models import LongTermMemory

# ============================================================
# CONFIG
# ============================================================

BACKEND_DIR = Path(__file__).resolve().parents[1]
VECTOR_STORE_DIR = BACKEND_DIR / "vector_store" / "faiss_memory"

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


embeddings = OpenAIEmbeddings(
    model=EMBEDDING_MODEL,
    api_key=os.getenv("OPENAI_API_KEY"),
)

llm = ChatOpenAI(
    model=LLM_MODEL,
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY"),
)


# ============================================================
# FAISS HELPERS
# ============================================================


@traceable(name="_vectorstore_exists", run_type="tool")
def _vectorstore_exists() -> bool:
    return (VECTOR_STORE_DIR / "index.faiss").exists() and (
        VECTOR_STORE_DIR / "index.pkl"
    ).exists()


@traceable(name="load_vectorstore", run_type="tool")
def load_vectorstore() -> Optional[FAISS]:
    """
    Load FAISS vector store if it exists.
    Returns None if no vector store has been created yet.
    """
    if not _vectorstore_exists():
        return None

    return FAISS.load_local(
        str(VECTOR_STORE_DIR),
        embeddings,
        allow_dangerous_deserialization=True,
    )


@traceable(name="save_vectorstore", run_type="tool")
def save_vectorstore(vectorstore: FAISS) -> None:
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(VECTOR_STORE_DIR))


@traceable(name="add_memory_to_faiss", run_type="tool")
def add_memory_to_faiss(memory_text: str, metadata: Dict[str, Any]) -> None:
    """
    Add one memory document to FAISS.
    If FAISS index does not exist yet, create it.
    """

    doc = Document(
        page_content=memory_text,
        metadata=metadata or {},
    )

    vectorstore = load_vectorstore()

    if vectorstore is None:
        vectorstore = FAISS.from_documents(
            documents=[doc],
            embedding=embeddings,
        )
    else:
        vectorstore.add_documents([doc])

    save_vectorstore(vectorstore)


# ============================================================
# MEMORY SUMMARIZATION
# ============================================================


@traceable(name="summarize_turn_to_memory", run_type="tool")
def summarize_turn_to_memory(
    user_message: str,
    agent_response: str,
    extracted_data: Optional[Dict[str, Any]] = None,
    result_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Convert one CRM interaction into a clean long-term memory text.
    This is the text that will be saved in DB and embedded in FAISS.
    """

    prompt = f"""
You are a CRM long-term memory summarizer.

Create a short useful memory for a CRM agent.

Keep only useful CRM context:
- contact name
- company name
- lead id
- interest
- status
- activity
- task
- approval decision
- user correction
- unresolved clarification
- important report preference

Do NOT include useless chat like greetings or thanks.
Do NOT invent information.

Return only the memory text as one short paragraph.

USER MESSAGE:
{user_message}

AGENT RESPONSE:
{agent_response}

EXTRACTED DATA:
{json.dumps(extracted_data or {}, ensure_ascii=False, indent=2)}

RESULT DATA:
{json.dumps(result_data or {}, ensure_ascii=False, indent=2)}
"""

    response = llm.invoke(prompt).content.strip()
    return response


@traceable(name="is_useful_memory", run_type="tool")
def is_useful_memory(memory_text: str) -> bool:
    """
    Avoid storing empty/useless memory.
    """

    if not memory_text:
        return False

    text = memory_text.strip().lower()

    useless = [
        "no useful memory",
        "nothing useful",
        "not useful",
        "greeting",
        "thanks",
    ]

    if len(text) < 20:
        return False

    return not any(item in text for item in useless)


# ============================================================
# DATABASE + FAISS SAVE
# ============================================================


@traceable(name="save_long_term_memory", run_type="tool")
def save_long_term_memory(
    db,
    session_id: Optional[str],
    memory_text: str,
    memory_type: str = "crm_interaction",
    contact_name: Optional[str] = None,
    company_name: Optional[str] = None,
    lead_id: Optional[int] = None,
    intent: Optional[str] = None,
    memory_metadata: Optional[Dict[str, Any]] = None,
    importance_score: float = 1.0,
) -> Dict[str, Any]:
    """
    Save memory in PostgreSQL and add the same memory text to FAISS.
    DB = source of truth.
    FAISS = semantic search layer.
    """

    if not is_useful_memory(memory_text):
        return {
            "success": False,
            "message": "Memory was not useful enough to store.",
        }

    memory = LongTermMemory(
        session_id=session_id,
        memory_type=memory_type,
        memory_text=memory_text,
        contact_name=contact_name,
        company_name=company_name,
        lead_id=lead_id,
        intent=intent,
        memory_metadata=memory_metadata or {},
        importance_score=importance_score,
    )

    db.add(memory)
    db.commit()
    db.refresh(memory)

    faiss_metadata = {
        "memory_id": memory.memory_id,
        "session_id": session_id,
        "memory_type": memory_type,
        "contact_name": contact_name,
        "company_name": company_name,
        "lead_id": lead_id,
        "intent": intent,
        "importance_score": importance_score,
    }

    add_memory_to_faiss(
        memory_text=memory_text,
        metadata=faiss_metadata,
    )

    return {
        "success": True,
        "message": "Long-term memory saved to DB and FAISS.",
        "memory_id": memory.memory_id,
        "memory_text": memory_text,
        "metadata": faiss_metadata,
    }


@traceable(name="save_turn_as_memory", run_type="tool")
def save_turn_as_memory(
    db,
    session_id: Optional[str],
    user_message: str,
    agent_response: str,
    extracted_data: Optional[Dict[str, Any]] = None,
    result_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Summarize a full agent turn, then store it as long-term memory.
    """

    memory_text = summarize_turn_to_memory(
        user_message=user_message,
        agent_response=agent_response,
        extracted_data=extracted_data,
        result_data=result_data,
    )

    metadata = {
        "user_message": user_message,
        "agent_response": agent_response,
        "extracted_data": extracted_data or {},
        "result_data": result_data or {},
    }

    contact_name = None
    company_name = None
    lead_id = None
    intent = None

    if isinstance(extracted_data, dict):
        contact_name = extracted_data.get("contact_name")
        company_name = extracted_data.get("company_name")
        lead_id = extracted_data.get("lead_id")
        intent = extracted_data.get("intent")

    if isinstance(result_data, dict):
        lead_id = result_data.get("lead_id") or lead_id
        intent = result_data.get("intent") or intent

    return save_long_term_memory(
        db=db,
        session_id=session_id,
        memory_type="crm_interaction",
        memory_text=memory_text,
        contact_name=contact_name,
        company_name=company_name,
        lead_id=lead_id,
        intent=intent,
        memory_metadata=metadata,
        importance_score=1.0,
    )


# ============================================================
# RETRIEVAL
# ============================================================


@traceable(name="retrieve_relevant_memories", run_type="tool")
def retrieve_relevant_memories(
    query: str,
    k: int = 3,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search FAISS for semantically relevant memories.
    If session_id is provided, same-session memories are preferred,
    but cross-session memories can still be returned.
    """

    vectorstore = load_vectorstore()

    if vectorstore is None:
        return []

    docs = vectorstore.similarity_search(query, k=max(k * 3, 5))

    results = []

    for doc in docs:
        metadata = doc.metadata or {}

        same_session = (
            session_id is not None and metadata.get("session_id") == session_id
        )

        results.append(
            {
                "memory_text": doc.page_content,
                "metadata": metadata,
                "same_session": same_session,
            }
        )

    # Prefer same-session memories first, then other relevant memories
    results = sorted(
        results,
        key=lambda item: (
            item.get("same_session", False),
            item.get("metadata", {}).get("memory_type") == "approval_decision",
            item.get("metadata", {}).get("importance_score", 1.0) or 1.0,
            item.get("metadata", {}).get("memory_id", 0) or 0,
        ),
        reverse=True,
    )

    return results[:k]


@traceable(name="build_memory_context", run_type="tool")
def build_memory_context(
    user_message: str,
    session_id: Optional[str] = None,
    k: int = 3,
) -> str:
    """
    Build readable memory context to inject into the Reasoning Agent prompt.
    """

    memories = retrieve_relevant_memories(
        query=user_message,
        session_id=session_id,
        k=k,
    )

    if not memories:
        return "No relevant long-term memories found."

    lines = ["Relevant long-term memories:"]

    for index, memory in enumerate(memories, start=1):
        metadata = memory.get("metadata", {})
        memory_text = memory.get("memory_text", "")

        tag = "same session" if memory.get("same_session") else "cross session"

        lines.append(f"{index}. ({tag}) {memory_text}")

        if (
            metadata.get("lead_id")
            or metadata.get("contact_name")
            or metadata.get("company_name")
        ):
            lines.append(
                f"   Metadata: lead_id={metadata.get('lead_id')}, "
                f"contact={metadata.get('contact_name')}, "
                f"company={metadata.get('company_name')}"
            )

    return "\n".join(lines)
