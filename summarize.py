import google.generativeai as genai
from dotenv import load_dotenv
import os
from flask import jsonify


def summarization(file_content):
    load_dotenv()
    ai_key: str = os.environ.get("GOOGLE_API_KEY")
    genai.configure(api_key=ai_key)
    model = genai.GenerativeModel('gemini-2.5-flash-lite')
    prompt = f'''
            아래 문서를 읽고 막 챕터마다(초론, 서론 같은거) 핵심내용을 요약해줘
            반드시 보기 좋은 Markdown형식으로 출력해줘
            헤더(#), 불릿 포인트(-), 굵은 글씨(**)를 적절히 사용해서 가독성을 높여줘.
            내용은 다음과 같아
            {file_content}
            '알겠습니다. 문서의 핵심 내용을 Markdown 형식으로 요약해 드리겠습니다.'라는 문장은 절대 넣지마
        '''
    response = model.generate_content(prompt)
    return response.text


def understand(file_content):
    load_dotenv()
    ai_key: str = os.environ.get("GOOGLE_API_KEY")
    genai.configure(api_key=ai_key)
    model = genai.GenerativeModel('gemini-2.5-flash-lite')
    prompt = f'''
                아래 문서를 읽고 이해하기 쉽도록 풀어서 설명해줘(특히 어려운 용어도 설명해주면서)
                반드시 보기 좋은 Markdown형식으로 출력해줘
                헤더(#), 불릿 포인트(-), 굵은 글씨(**)를 적절히 사용해서 가독성을 높여줘.
                참고로 알겠습니다. 같은 문장은 넣지 말아줘
                내용은 다음과 같아
                {file_content}
            '''
    response = model.generate_content(prompt)
    return response.text



