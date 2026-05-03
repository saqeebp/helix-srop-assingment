import asyncio
import httpx
import json

async def test():
    async with httpx.AsyncClient() as client:
        # Create a session
        resp = await client.post(
            'http://localhost:8000/v1/sessions',
            json={'user_id': 'u_test_001', 'plan_tier': 'pro'}
        )
        session_id = resp.json()['session_id']
        print(f'Session: {session_id}\n')
        
        # Send an account question
        try:
            chat_resp = await client.post(
                f'http://localhost:8000/v1/chat/{session_id}',
                json={'content': 'Show me my recent builds'},
                timeout=30
            )
            print(f'Status: {chat_resp.status_code}')
            result = chat_resp.json()
            print(f'Routed to: {result.get("routed_to")}')
            print(f'\nReply:\n{result.get("reply")}')
        except Exception as e:
            print(f'Error: {e}')

asyncio.run(test())
