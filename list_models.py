import google.generativeai as genai
from app.config.settings import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

models = genai.list_models()

for model in models:
    print("NAME:", model.name)

    try:
        print("METHODS:", model.supported_generation_methods)
    except:
        pass

    print("-" * 50)