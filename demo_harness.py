import asyncio
import httpx
import uvicorn
import threading
import time
import json
from src.mcp_server import (
    write_agent_memory,
    read_agent_memory,
    create_execution_plan,
    mark_plan_step_complete,
    create_document,
    update_document,
    read_document_chunk
)

async def run_demo():
    print("🚀 Starting Harness Engineering Demo...\n")
    
    # 1. Agent Memory
    print("🧠 [1] Testing Agent Memory...")
    res1 = await write_agent_memory("current_goal", "Write a 50-word introduction about Harness Engineering")
    print("  -> Write Memory Result:", json.loads(res1))
    
    res2 = await read_agent_memory("current_goal")
    print("  -> Read Memory Result:", json.loads(res2))
    print()

    # 2. Execution Planning
    print("📋 [2] Testing Execution Planning...")
    steps = ["Create intro document", "Add content with intent", "Read a chunk of the document"]
    res3 = await create_execution_plan("Intro Workflow", steps)
    print("  -> Created Plan:", json.loads(res3))
    print()

    # 3. Document Creation (Standard Tool)
    print("📄 [3] Testing Document Creation...")
    res4 = await create_document("Harness Intro", "This is an introduction.")
    doc_id = json.loads(res4).get("id")
    print(f"  -> Created Document ID: {doc_id}")
    
    # Complete step 1
    await mark_plan_step_complete(0)
    print("  -> Marked Plan Step 1 Complete.")
    print()

    # 4. Destructive Action with Intent (Authorization)
    print("🛡️ [4] Testing Tool Authorization (Intent)...")
    content = "Harness Engineering is the discipline of designing the scaffolding around an AI agent."
    
    # Failing intentionally without intent
    res5 = await update_document(doc_id, content=content, intent="")
    print("  -> Update WITHOUT intent:", json.loads(res5))
    
    # Succeeding with intent
    intent = "I need to update the document with the final introductory text as per the user's request."
    res6 = await update_document(doc_id, content=content, intent=intent)
    print("  -> Update WITH intent:", json.loads(res6))
    
    # Complete step 2
    await mark_plan_step_complete(1)
    print("  -> Marked Plan Step 2 Complete.")
    print()

    # 5. Context Compaction
    print("📦 [5] Testing Context Compaction...")
    res7 = await read_document_chunk(doc_id, start_line=0, end_line=1)
    print("  -> Read Document Chunk:", json.loads(res7))
    
    # Complete step 3
    await mark_plan_step_complete(2)
    print("  -> Marked Plan Step 3 Complete.")
    print("\n✅ Demo finished successfully! Check your admin_gui for the live tracking of these intents.")

def start_server():
    from src.web_server import app
    import logging
    logging.getLogger("uvicorn.error").setLevel(logging.ERROR)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="error")

if __name__ == "__main__":
    # Start web server in background
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Give server time to boot
    time.sleep(2)
    
    # Run async demo
    asyncio.run(run_demo())
