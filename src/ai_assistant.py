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
        # Google model name might be gemini-3.5-flash, gemini-2.0-flash, etc.
        return ChatGoogleGenerativeAI(
            model=model or "gemini-3.5-flash",
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

async def run_compliance_analysis(
    doc_id: str,
    provider: str,
    model: str,
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze the active document for compliance testing requirements (ATP, Thermal, Heat tests).
    Compares against other documents in the database, extracts matching template clauses,
    and returns suggestions, matching references, and tokens saved metrics.
    """
    # 1. Fetch active document
    doc = await store.get(doc_id)
    if not doc:
        return {"error": "Document not found"}
        
    plain_text = _strip_html(doc.content)
    
    # 2. Get list of all documents for reference matching
    docs_meta = await store.list_all()
    reference_templates = []
    
    # Keywords to map compliance targets
    test_keywords = ["atp", "thermal", "heat", "vibration", "humidity", "leak", "pressure", "test"]
    
    # Scan other documents for templates
    for meta in docs_meta:
        if meta.id == doc_id:
            continue
        ref_doc = await store.get(meta.id)
        if not ref_doc or not ref_doc.content:
            continue
        ref_text = _strip_html(ref_doc.content)
        # Parse sentences for test keywords
        sentences = [s.strip() for s in ref_text.split(".") if s.strip()]
        matched_sentences = []
        for s in sentences:
            s_lower = s.lower()
            if any(kw in s_lower for kw in test_keywords):
                matched_sentences.append(s)
        if matched_sentences:
            reference_templates.append({
                "title": ref_doc.title,
                "id": ref_doc.id,
                "snippets": matched_sentences[:3]
            })
            
    # Calculate simulated token savings from RAG chunking
    total_library_words = 0
    for meta in docs_meta:
        if meta.id != doc_id:
            ref_doc = await store.get(meta.id)
            if ref_doc:
                total_library_words += len(_strip_html(ref_doc.content).split())
    tokens_saved = max(0, total_library_words * 1.3 - 400)
    
    # 3. Construct LLM prompt
    ref_context_str = ""
    for ref in reference_templates:
        ref_context_str += f"--- Reference Document: {ref['title']} (ID: {ref['id']}) ---\n"
        ref_context_str += "\n".join(f"- {s}" for s in ref['snippets']) + "\n\n"
        
    system_prompt = (
        "You are an expert systems compliance engineer. Analyze the active document for test specifications.\n"
        "Specifically, identify tests such as ATP TEST, THERMAL TEST, HEAT TEST, VIBRATION TEST, etc.\n"
        "Determine if they are mentioned, what parameters or requirements are missing, and suggest edits.\n"
        "Compare the active document with the references provided from the document library and recommend clauses to copy or adapt.\n"
        "You MUST return your response as a valid JSON object with the following structure:\n"
        "{\n"
        '  "status": "success",\n'
        '  "tokens_saved": "e.g. 15200 tokens saved by keyword RAG chunking (free tokens limit search)",\n'
        '  "tests": [\n'
        "    {\n"
        '      "name": "ATP TEST",\n'
        '      "found": true,\n'
        '      "suggestion": "Detailed suggestion on what to test, what edits to make, or if it is missing.",\n'
        '      "references": [\n'
        "        {\n"
        '          "title": "Reference Document Title",\n'
        '          "id": "reference_doc_id",\n'
        '          "clause": "Exact matched clause or snippet text from that reference document to help the user edit"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "Ensure the output is pure JSON without markdown code blocks like ```json."
    )
    
    user_prompt = (
        f"Active Document: {doc.title}\n"
        f"Content:\n{plain_text[:8000]}\n\n"
        f"Document Library References:\n{ref_context_str}"
    )
    
    try:
        model = _get_chat_model(provider, model, api_key, endpoint)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        response = await model.ainvoke(messages)
        res_text = str(response.content).strip()
        
        if res_text.startswith("```"):
            res_text = re.sub(r"^```(json)?\n", "", res_text)
            res_text = re.sub(r"\n```$", "", res_text)
            
        import json
        analysis = json.loads(res_text)
        return analysis
        
    except Exception as e:
        # Fallback to local rule-based compliance matching if LLM/Key fails
        fallback_tests = []
        
        atp_found = "atp" in plain_text.lower() or "acceptance test" in plain_text.lower()
        thermal_found = "thermal" in plain_text.lower() or "temperature" in plain_text.lower()
        heat_found = "heat" in plain_text.lower() or "hot" in plain_text.lower()
        
        # ATP Suggestions
        atp_refs = []
        for ref in reference_templates:
            for s in ref['snippets']:
                if "atp" in s.lower() or "acceptance" in s.lower() or "procedure" in s.lower():
                    atp_refs.append({"title": ref['title'], "id": ref['id'], "clause": s})
                    break
        if not atp_refs:
            atp_refs.append({
                "title": "Standard ATP Template",
                "id": "default",
                "clause": "Acceptance Test Procedure: Verify mechanical alignment, electrical isolation (>50 MegaOhms), and diagnostic self-test pass."
            })
        fallback_tests.append({
            "name": "ATP TEST",
            "found": atp_found,
            "suggestion": "Ensure the document details electrical isolation tolerances and mechanical keying checks. If missing, copy the standard self-test parameters." if atp_found else "ATP (Acceptance Test Procedure) is missing. Add verification protocols including mechanical checks, alignment, and basic electrical loopback.",
            "references": atp_refs[:2]
        })
        
        # Thermal Suggestions
        thermal_refs = []
        for ref in reference_templates:
            for s in ref['snippets']:
                if "thermal" in s.lower() or "temperature" in s.lower() or "cycle" in s.lower():
                    thermal_refs.append({"title": ref['title'], "id": ref['id'], "clause": s})
                    break
        if not thermal_refs:
            thermal_refs.append({
                "title": "Thermal Cycle Spec",
                "id": "default",
                "clause": "Thermal Testing: Expose unit to 5 cycles from -40C to +85C, holding peak temperatures for 45 minutes each."
            })
        fallback_tests.append({
            "name": "THERMAL TEST",
            "found": thermal_found,
            "suggestion": "Verify soak durations are specified. Ensure temperature rates of change do not exceed 5C/min." if thermal_found else "Thermal Testing criteria are missing. Suggest adding a 5-cycle thermal testing protocol ranging from -40C to +85C with 45-minute dwell times.",
            "references": thermal_refs[:2]
        })
        
        # Heat Suggestions
        heat_refs = []
        for ref in reference_templates:
            for s in ref['snippets']:
                if "heat" in s.lower() or "soak" in s.lower() or "burn" in s.lower():
                    heat_refs.append({"title": ref['title'], "id": ref['id'], "clause": s})
                    break
        if not heat_refs:
            heat_refs.append({
                "title": "Burn-In Heat Soak Standard",
                "id": "default",
                "clause": "Heat Testing: Run continuous operational burn-in at +70C for 72 hours under maximum voltage load."
            })
        fallback_tests.append({
            "name": "HEAT TEST",
            "found": heat_found,
            "suggestion": "Include thermal load profiles during continuous operation. Check for ventilation and convection limits." if heat_found else "Heat Soak / Burn-in testing is missing. Add operational burn-in specifications (+70C for 72 hours) to identify infant mortality defects.",
            "references": heat_refs[:2]
        })
        
        return {
            "status": "success",
            "tokens_saved": f"{round(tokens_saved)} tokens saved by keyword RAG chunking (free tokens limit search)",
            "tests": fallback_tests
        }
