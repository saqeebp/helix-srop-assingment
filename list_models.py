import google.generativeai as genai
from app.settings import settings

if settings.google_api_key:
    genai.configure(api_key=settings.google_api_key)
    
    models = genai.list_models()
    print("Available models:")
    for m in models:
        if 'embed' in m.name.lower():
            print(f"  - {m.name}")
            print(f"    Supported methods: {m.supported_generation_methods}")
