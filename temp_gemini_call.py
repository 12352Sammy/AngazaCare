import os
import traceback
from dotenv import load_dotenv
load_dotenv()
import google.generativeai as genai

print('API KEY LOADED', bool(os.getenv('GEMINI_API_KEY')))
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

system_prompt = (
    "You are AngazaCare AI, a compassionate mental health companion. Respond with empathy and care. "
    "Never diagnose. Always encourage professional help for serious concerns. Keep responses under 100 words."
)

messages = [
    {"role": "system", "parts": [system_prompt]},
    {"role": "user", "parts": ["hello"]},
]

try:
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    response = model.generate_content(messages)
    print('RESPONSE OBJ', type(response))
    try:
        print('RESPONSE TEXT', getattr(response, 'text', None))
    except Exception as e:
        print('TEXT ACCESS ERROR', e)
    print('RESPONSE ATTRS', [a for a in dir(response) if not a.startswith('_')][:50])
except Exception as e:
    print('ERROR', type(e).__name__, e)
    traceback.print_exc()
