import subprocess
from dotenv import load_dotenv
import os
import google.generativeai as genai

load_dotenv()  # env파일에서 환경변수 로드
ai_key: str = os.environ.get("GOOGLE_API_KEY")

model_name = 'gemini-2.5-flash-lite'
model = genai.GenerativeModel(model_name)

command = ["pdf2zh", "2407.14361v1.pdf", "-li", "en", "-lo", "ko", "-s", "google:gemini"]

env = os.environ.copy()
env["GEMINI_API_KEY"] = ai_key
env["GEMINI_MODEL"] = model_name
subprocess.run(command, check=True, env=env)

