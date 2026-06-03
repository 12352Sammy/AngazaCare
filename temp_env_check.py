import os
from dotenv import load_dotenv
load_dotenv()
print('KEY LOADED', bool(os.getenv('GEMINI_API_KEY')))
print('KEY LEN', len(os.getenv('GEMINI_API_KEY') or ''))
import google.generativeai as genai
print('GENAI OK', hasattr(genai, 'GenerativeModel'), getattr(genai, '__version__', None))
