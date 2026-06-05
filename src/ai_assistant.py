"""
LangChain-powered AI Assistant service.
Handles dynamic model initialization, prompt construction, and RAG over documents.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

# Load environment variables from .env if present and not already loaded
if not os.environ.get("GEMINI_API_KEY"):
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _env_path = os.path.join(_project_root, ".env")
    if os.path.exists(_env_path):
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#"):
                    continue
                if "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"').strip("'")
                    if _k not in os.environ:
                        os.environ[_k] = _v

# Import LangChain components
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# Document stores for RAG
from .storage import store

class AIChatRequest(BaseModel):
    provider: str  # "openai", "google", "anthropic", "ollama"
    model: str
    api_key: Optional[str] = None
    endpoint: Optional[str] = None  # for custom endpoints like Ollama
    message: str
    chat_history: List[Dict[str, str]] = []  # [{"role": "user", "content": "..."}]
    active_doc_id: Optional[str] = None
    scope: str = "document"  # "document", "all", "general"

class AIActionRequest(BaseModel):
    provider: str
    model: str
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    action: str  # "summarize", "polish", "translate", "outline"
    text: str  # selection or full doc content
    target_lang: Optional[str] = None  # for translation

def _get_chat_model(provider: str, model: str, api_key: Optional[str] = None, endpoint: Optional[str] = None) -> Any:
    """Initialize a LangChain chat model based on the selected provider and key."""
    provider = provider.lower()
    
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "gpt-4o-mini",
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            temperature=0.7,
        )
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        # Google model name might be gemini-1.5-pro, gemini-1.5-flash, etc.
        return ChatGoogleGenerativeAI(
            model=model or "gemini-1.5-flash",
            google_api_key=api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            temperature=0.7,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or "claude-3-5-sonnet-20240620",
            anthropic_api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.7,
        )
    elif provider == "ollama":
        from langchain_openai import ChatOpenAI
        # Ollama supports OpenAI compatibility out of the box
        base_url = endpoint or "http://localhost:11434/v1"
        return ChatOpenAI(
            model=model or "llama3",
            api_key="ollama",  # dummy key
            base_url=base_url,
            temperature=0.7,
        )
    else:
        raise ValueError(f"Unsupported AI provider: {provider}")

def _strip_html(html: str) -> str:
    """Helper to convert HTML to plain text for LLM context."""
    if not html:
        return ""
    # Basic tag removal
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode basic HTML entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    # Clean up spacing
    return re.sub(r"\s+", " ", text).strip()

async def get_relevant_context(query: str, active_doc_id: Optional[str], scope: str) -> str:
    """
    Retrieve document context based on search scope.
    In-memory RAG:
    - active document: load entire doc content.
    - all documents: search all docs and retrieve matching snippets.
    """
    if scope == "document" and active_doc_id:
        doc = await store.get(active_doc_id)
        if doc:
            plain_text = _strip_html(doc.content)
            return f"--- ACTIVE DOCUMENT: {doc.title} ---\n{plain_text}\n--- END ACTIVE DOCUMENT ---"
        return "No active document content found."
        
    elif scope == "all":
        docs_meta = await store.list_all()
        snippets = []
        
        # Simple TF-IDF/Keyword matching for context retrieval
        query_words = set(re.findall(r"\w+", query.lower()))
        
        for meta in docs_meta:
            doc = await store.get(meta.id)
            if not doc or not doc.content:
                continue
            
            plain_text = _strip_html(doc.content)
            # Split doc into paragraphs
            paragraphs = [p.strip() for p in plain_text.split(".") if p.strip()]
            
            matched_paragraphs = []
            for p in paragraphs:
                p_lower = p.lower()
                # Score paragraph based on overlapping query words
                score = sum(1 for w in query_words if w in p_lower)
                if score > 0:
                    matched_paragraphs.append((score, p))
            
            # Sort paragraphs by score descending and take top 2
            matched_paragraphs.sort(key=lambda x: x[0], reverse=True)
            for _, p in matched_paragraphs[:2]:
                snippets.append(f"Document: '{doc.title}'\nSnippet: ... {p} ...")
                
        if snippets:
            return "--- RELEVANT CONTEXT FROM LIBRARY ---\n" + "\n\n".join(snippets) + "\n--- END CONTEXT ---"
        else:
            # If no snippets found, list available documents
            titles = [f"- {d.title} (ID: {d.id})" for d in docs_meta]
            return "--- DOCUMENT LIBRARY ---\nAvailable documents:\n" + "\n".join(titles) + "\n--- END LIBRARY ---"
            
    return ""  # General chat, no extra document context

async def chat_with_assistant(req: AIChatRequest) -> str:
    """Run a conversational turn with LangChain, injecting document context."""
    # 1. Initialize model
    model = _get_chat_model(req.provider, req.model, req.api_key, req.endpoint)
    
    # 2. Retrieve document context
    context = await get_relevant_context(req.message, req.active_doc_id, req.scope)
    
    # 3. Construct chat prompt
    system_prompt = (
        "You are a helpful, professional AI Writing Assistant embedded in a collaborative rich-text editor.\n"
        "Your goal is to assist the user in drafting, editing, formatting, and analyzing documents.\n"
        "Always respond in clean Markdown. "
    )
    
    if context:
        system_prompt += (
            "\nHere is the document context retrieved for this conversation:\n"
            f"{context}\n\n"
            "Use the provided document context to answer questions, explain concepts, or suggest rewrites. "
            "If the user asks you to write or rewrite text, provide clear suggestions. "
            "If the user asks questions unrelated to the context, answer them politely anyway."
        )
    else:
        system_prompt += "\nFeel free to help the user with general editing, planning, and coding tasks."

    # 4. Parse history
    messages: List[BaseMessage] = [SystemMessage(content=system_prompt)]
    
    for msg in req.chat_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
            
    # Add current user message
    messages.append(HumanMessage(content=req.message))
    
    # 5. Run LLM
    response = await model.ainvoke(messages)
    return str(response.content)

async def run_document_action(req: AIActionRequest) -> str:
    """Execute standard document prompt templates using LangChain."""
    model = _get_chat_model(req.provider, req.model, req.api_key, req.endpoint)
    
    plain_text = _strip_html(req.text)
    if not plain_text:
        return "No text provided to analyze."
        
    action = req.action.lower()
    
    if action == "summarize":
        system_prompt = "You are an expert summarizer. Summarize the provided text in a concise, bulleted format. Focus on key points, takeaways, and action items."
        user_prompt = f"Please summarize the following document:\n\n{plain_text}"
    elif action == "polish":
        system_prompt = (
            "You are a professional editor. Improve the style, flow, grammar, and readability of the provided text.\n"
            "Keep the original meaning and tone, but make it sound more professional and clean.\n"
            "Output the polished text directly, without introductory remarks."
        )
        user_prompt = f"Please polish this text:\n\n{plain_text}"
    elif action == "translate":
        target = req.target_lang or "Spanish"
        system_prompt = (
            f"You are a professional translator. Translate the provided text into {target}.\n"
            "Keep any technical terms or specific formatting intact. "
            "Output the translation directly, without introductory remarks."
        )
        user_prompt = f"Translate the following text into {target}:\n\n{plain_text}"
    elif action == "outline":
        system_prompt = "You are a structural content editor. Create a clean, hierarchical outline (headers, sub-bullets) of the provided text to show its main sections and flow."
        user_prompt = f"Create an outline for this text:\n\n{plain_text}"
    else:
        raise ValueError(f"Unknown action: {req.action}")
        
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    response = await model.ainvoke(messages)
    return str(response.content)
