import asyncio
from app.agents.tools.search_docs import search_docs

async def test_search():
    try:
        result = await search_docs("How do I rotate my deploy key?", k=5)
        print(f"Search result: {result}")
        print(f"Number of results: {len(result.get('results', []))}")
        if result.get('results'):
            for r in result['results']:
                print(f"  - {r['chunk_id']}: {r['content'][:100]}...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test_search())
