import asyncio
import sys
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

async def run_mcp_test():
    print("🤖 Starting AI Brain Test (MCP Client Simulation)...")
    print("==================================================")
    
    # Configure the client to connect to our MCP server via stdio
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["main.py", "mcp"],
    )
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # 1. Initialize the session
                print("🔌 Connecting to MCP Server...")
                await session.initialize()
                print("✅ Connected successfully!\n")
                
                # 2. List available tools
                print("🔍 Discovering tools...")
                tools = await session.list_tools()
                tool_names = [tool.name for tool in tools.tools]
                print(f"✅ Found {len(tool_names)} tools: {', '.join(tool_names[:3])}...\n")
                
                # 3. Simulate AI creating a document
                print("📝 Simulating AI: Creating a new document...")
                create_result = await session.call_tool(
                    "create_document", 
                    arguments={
                        "title": "AI Test Document",
                        "content": "<h1>Hello from the AI!</h1><p>I just created this document using the MCP protocol.</p>",
                        "tags": ["test", "ai", "mcp"]
                    }
                )
                
                # The result.content is usually a list of TextContent objects
                # We'll parse out the document ID from the text response
                response_text = create_result.content[0].text
                print(f"✅ AI received response:\n   {response_text}\n")
                
                import json
                try:
                    data = json.loads(response_text)
                    doc_id = data.get("id")
                    if not doc_id:
                        print("❌ Could not find 'id' in JSON response.")
                        return
                except json.JSONDecodeError:
                    print("❌ Could not parse JSON response.")
                    return
                
                # 4. Wait a moment, then simulate AI updating the document
                print("⏳ Waiting 3 seconds (check your web browser if you have the editor open!)...")
                await asyncio.sleep(3)
                
                print("✍️ Simulating AI: Updating the document...")
                update_result = await session.call_tool(
                    "update_document",
                    arguments={
                        "doc_id": doc_id,
                        "content": "<h1>Hello from the AI!</h1><p>I just created this document using the MCP protocol.</p><br><p><strong>Update:</strong> I have now edited this document live! Did you see it update on the screen?</p>",
                        "title": "AI Test Document (Updated)",
                        "summary": "Added a new paragraph to test live updates"
                    }
                )
                
                print(f"✅ AI received response:\n   {update_result.content[0].text}\n")
                
                # 5. Read version history
                print("📜 Simulating AI: Checking version history...")
                history_result = await session.call_tool(
                    "get_version_history",
                    arguments={"doc_id": doc_id}
                )
                print(f"✅ AI received history:\n   {history_result.content[0].text[:100]}...\n")
                
                print("==================================================")
                print("🎉 SUCCESS! The MCP Server is fully operational.")
                print("The AI Brain can successfully control the document editor.")
                
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")

if __name__ == "__main__":
    asyncio.run(run_mcp_test())
