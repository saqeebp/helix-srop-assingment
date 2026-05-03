import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as client:
        # Create a session
        resp = await client.post(
            'http://localhost:8000/v1/sessions',
            json={'user_id': 'test_user_001', 'plan_tier': 'pro'}
        )
        print(f'Session response: {resp.json()}')
        session_id = resp.json()['session_id']
        print(f'Session created: {session_id}')
        
        # Send a knowledge question
        chat_resp = await client.post(
            f'http://localhost:8000/v1/chat/{session_id}',
            json={'user_message': 'How do I deploy a key?'}
        )
        result = chat_resp.json()
        print(f'Status: {chat_resp.status_code}')
        print(f'Routed to: {result.get("routed_to")}')
        print(f'Reply preview: {result.get("reply", "")[:200]}...')

asyncio.run(test())
