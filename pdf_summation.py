from pypdf import PdfReader
import google.generativeai as genai

def extract_text_from_pdf(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        full_text = ''

        for page in reader.pages:
            text = page.extract_text()
            if text:
                full_text += text + '\n'
        return full_text
    except Exception as e:
        return f'error {e}'


def summarize_text_with_gemini(text_to_summarize, api_key):
    try:
        genai.configure(api_key=api_key)
        model_name = 'gemini-2.5-flash-lite'
        model = genai.GenerativeModel(model_name)
        style_css = """
        <style>
            body {
                font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
                line-height: 1.6;
                color: #333;
                max_width: 800px;
                margin: 40px auto;
                padding: 20px;
                background-color: #f9f9f9;
            }
            h1 {
                color: #2c3e50;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
                font-size: 28px;
            }
            h2 {
                color: #2980b9;
                margin-top: 30px;
                font-size: 22px;
            }
            h3 {
                color: #16a085;
                margin-top: 20px;
                font-size: 18px;
            }
            p {
                margin-bottom: 15px;
                text-align: justify;
                background-color: #fff;
                padding: 15px;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.05);
            }
            ul, ol {
                background-color: #fff;
                padding: 15px 15px 15px 40px;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.05);
            }
            li {
                margin-bottom: 5px;
            }
        </style>
        """
        #           """
        prompt = f'''
        {text_to_summarize}
        출력은 HTML 문서 형태로 만들어줘. 다만 글은 모두 한국어로 해줘
        제목은 h1, 큰 목차는 h2, 작은 목차는 h3로 만들어줘.
        본문 문장은 p 태그로 감싸줘.
        원하는 css스타일은 다음과 같아
        {style_css}
        그리고 내용 요약도 부탁해. 오로지 코드만 출력해줘(이미지는 필요없어)
        '''
        response = model.generate_content(prompt)
        return response.text[8:-3]
    except Exception as e:
        return f"오류 발생: {e}"


from dotenv import load_dotenv
import os

load_dotenv()  # env파일에서 환경변수 로드
ai_key: str = os.environ.get("GOOGLE_API_KEY")

pdf_file = '2407.14361v1.pdf'
extract_text = extract_text_from_pdf(pdf_file)
summarize = summarize_text_with_gemini(extract_text, ai_key)

print(summarize)
print(len(summarize))

with open('result.html','w', encoding='utf-8') as f:
    f.write(summarize)
