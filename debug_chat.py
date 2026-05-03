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
        print(f'Session: {session_id}')
        
        # Send a knowledge question
        try:
            chat_resp = await client.post(
                f'http://localhost:8000/v1/chat/{session_id}',
                json={'content': 'How do I deploy a key?'},
                timeout=30
            )
            print(f'Status: {chat_resp.status_code}')
            print(f'Response: {json.dumps(chat_resp.json(), indent=2)}')
        except Exception as e:
            print(f'Error: {e}')

asyncio.run(test())
