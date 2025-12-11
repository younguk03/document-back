import os
from supabase import create_client, Client
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import traceback
import uuid
import subprocess
import fitz  # PyMuPDF (코드 최상단에 추가 권장)
from werkzeug.utils import secure_filename
import gc

from summarize import summarization, understand
import google.generativeai as genai


app = Flask(__name__)
CORS(app)

load_dotenv()  # env파일에서 환경변수 로드

url: str = os.environ.get("SUPABASE_URL")
# key: str = os.environ.get("SUPABASE_KEY")
key: str = os.environ.get("SUPABASE_SERVICE_KEY")

STORAGE_BUCKET = "files"  # Supabase Storage에 생성한 버킷 이름

supabase: Client = create_client(url, key)

# 임시 파일 저장을 위한 안전한 디렉터리 설정
TEMP_DIR = os.path.join(os.getcwd(), 'temp_pdfs')
os.makedirs(TEMP_DIR, exist_ok=True)  # 디렉터리가 없으면 생성

try:
    supabase: Client = create_client(url, key)
except Exception as e:
    print(f"Supabase 클라이언트 초기화 오류: {e}")
    supabase = None

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.route('/')
def home():
    return "Flask-Supabase Auth API"


# 회원가입
@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    client_name = data.get('client_name')
    email = data.get('email')
    password = data.get('password')

    if not all([client_name, email, password]):
        return jsonify({"error": "이름, 이메일, 비밀번호는 필수입니다."}), 400

    try:
        # Supabase Auth 회원 생성
        auth_res = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "client_name": client_name
                }
            }
        })
        if not auth_res.user:
            return jsonify({"error": "회원가입 실패"}), 400

        user_id = auth_res.user.id

        # users 테이블에 추가 정보 저장
        # supabase.table("users").insert({
        #     "id": user_id,
        #     "nickname": nickname
        # }).execute()

        return jsonify({"message": "회원가입 성공", "user_id": user_id}), 201

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# 로그인
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    try:
        auth_res = supabase.auth.sign_in_with_password({'email': email, 'password': password})
        if not auth_res.user:
            return jsonify({'error', '로그인 실패'}), 401
        access_token = auth_res.session.access_token
        user_id = auth_res.user.id

        client_name = None
        if auth_res.user.user_metadata:
            client_name = auth_res.user.user_metadata.get('client_name')

        # 추가정보
        # user_info = supabase.table("users").select("*").execute()
        # client_name = user_info.data[0]['client_name'] if user_info.data else None
        return jsonify({
            "message": "로그인 성공",
            "token": access_token,
            "user": {
                "id": user_id,
                "email": email,
                'client_name': client_name
            }
        }), 200
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500


# 토큰 인증 레코레이터
from functools import wraps


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('Authorization', None)
        try:
            if not token:
                return jsonify({'error': '토큰이 없습니다.'}), 401
            if token.startswith('Bearer'):
                token = token.split('')[1]

            user = supabase.auth.get_user(token)
            if not user.user:
                return jsonify({"error": "유효하지 않은 토큰"}), 401
            request.user = user.user
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': f'토큰 검증 실패: {str(e)}'}), 401
        return wrapper



# 데이터베이스 문제때문에 청소하기 위해 만든 함수
def clean_text_for_db(text):
    if not text:
        return ""
    # 널 바이트(\x00)를 빈 문자열로 치환하여 제거
    return text.replace("\x00", "")


@app.route('/api/upload', methods=['POST'])
def upload_translate():
    logger.info("========== [프로세스 시작] ==========")
    
    # 0. 메모리 정리 (시작 전 청소)
    gc.collect()

    # 1. 파일 유효성 검사
    if 'file' not in request.files:
        return jsonify({"error": "파일이 전송되지 않았습니다."}), 400

    file = request.files['file']
    user_id = request.form.get('user_id')

    if not user_id or user_id == 'undefined':
        return jsonify({"error": "로그인 정보(User ID)가 유실되었습니다."}), 400

    # 2. 파일명 및 경로 설정
    original_title = secure_filename(file.filename)
    unique_id = uuid.uuid4().hex
    
    input_filename = f"original_{unique_id}.pdf"
    final_output_filename = f"translated_{unique_id}.pdf"
    
    input_path = os.path.join(TEMP_DIR, input_filename)
    final_output_path = os.path.join(TEMP_DIR, final_output_filename)
    prompt_path = os.path.join(TEMP_DIR, f"prompt_{unique_id}.txt")

    # 정리 대상 파일 리스트
    files_to_clean = [input_path, prompt_path]

    try:
        # ---------------------------------------------------------
        # A. 원본 파일 로컬 저장
        # ---------------------------------------------------------
        file.save(input_path)
        logger.info(f"📂 원본 저장 완료: {input_path}")

        # ---------------------------------------------------------
        # B. [최적화] 텍스트 추출 (원본 파일 사용 & 제한 읽기)
        # 번역본을 기다리지 않고 원본에서 바로 추출하여 메모리와 시간을 아낍니다.
        # ---------------------------------------------------------
        text_content = ""
        try:
            with fitz.open(input_path) as doc:
                # 최대 5페이지만 읽거나 3000자 넘으면 중단 (메모리 절약)
                for i, page in enumerate(doc):
                    if i >= 5: break 
                    text_content += page.get_text()
                    if len(text_content) > 4000: break
            
            logger.info(f"📝 텍스트 추출 완료 ({len(text_content)}자)")
        except Exception as e:
            logger.error(f"⚠️ 텍스트 추출 실패: {e}")
            text_content = ""

        # ---------------------------------------------------------
        # C. AI 요약 생성 (가벼운 작업 먼저 실행)
        # ---------------------------------------------------------
        try:
            # 요약용 텍스트는 3000자로 자름
            summary_input = text_content[:3000] if text_content else "내용 없음"
            pdf_summary = summarization(summary_input)
            pdf_understand = understand(summary_input)
        except Exception as e:
            logger.error(f"⚠️ 요약 생성 에러: {e}")
            pdf_summary = "요약 생성 실패"
            pdf_understand = ["핵심 내용을 추출하지 못했습니다."]

        # ---------------------------------------------------------
        # D. Supabase 원본 업로드 (안전하게 먼저 확보)
        # ---------------------------------------------------------
        with open(input_path, "rb") as f:
            path = f"originals/{input_filename}"
            supabase.storage.from_(STORAGE_BUCKET).upload(path, f, file_options={"content-type": "application/pdf"})
            original_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(path)

        # ---------------------------------------------------------
        # E. 번역 실행 (가장 무거운 작업 - 실패 가능성 있음)
        # ---------------------------------------------------------
        translate_success = False
        translated_url = None
        
        # 메모리 확보를 위해 강제 GC 실행
        gc.collect() 

        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            try:
                # 프롬프트 파일 생성
                with open(prompt_path, "w", encoding="utf-8") as f:
                    f.write("전문 용어 제외하고 한국어로 번역. 코드나 논문 제목은 원문 유지.")

                env = os.environ.copy()
                env['GEMINI_API_KEY'] = api_key
                
                # 타임아웃 120초로 증가 (무료 플랜 성능 고려)
                # 주의: Render 무료 플랜은 subprocess 실행 시 메모리가 튀면 바로 Kill 당함
                command = [
                    "pdf2zh", input_path,
                    "-li", "en", "-lo", "ko",
                    "-s", "google:gemini",
                    "-o", TEMP_DIR,
                    "--prompt", prompt_path,
                    "-t", "1" # 스레드 1개로 제한 (중요!)
                ]
                
                logger.info("🤖 번역 프로세스 시작...")
                subprocess.run(command, check=True, env=env, capture_output=True, timeout=120)

                # 번역 결과물 찾기 로직
                files_in_dir = os.listdir(TEMP_DIR)
                target_prefix = input_filename.replace('.pdf', '')
                
                for fname in files_in_dir:
                    if fname.endswith("-mono.pdf") and (target_prefix in fname):
                        os.rename(os.path.join(TEMP_DIR, fname), final_output_path)
                        files_to_clean.append(final_output_path)
                        
                        # 번역본 업로드
                        with open(final_output_path, "rb") as f_trans:
                            path_trans = f"translated/{final_output_filename}"
                            supabase.storage.from_(STORAGE_BUCKET).upload(path_trans, f_trans, file_options={"content-type": "application/pdf"})
                            translated_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(path_trans)
                        
                        translate_success = True
                        logger.info("✅ 번역 및 업로드 성공")
                        break
                        
            except subprocess.TimeoutExpired:
                logger.error("⏰ 번역 시간 초과 (Timeout)")
            except Exception as e:
                logger.error(f"⚠️ 번역 프로세스 실패 (메모리 부족 등): {e}")
        
        # ---------------------------------------------------------
        # F. DB 저장 (번역 실패했어도 원본 데이터는 저장)
        # ---------------------------------------------------------
        db_data = {
            'user_id': user_id,
            'original_title': original_title,
            'translated_title': f"{original_title} (번역본)" if translate_success else original_title,
            'original_url': original_url,
            'translated_url': translated_url, # None이면 DB에 null로 들어감
            'summarize': pdf_summary,
            'understand': pdf_understand,
            'extracted_text': text_content[:5000]
        }

        response = supabase.table('Files').insert(db_data).execute()
        new_file_id = response.data[0]['id']

        # 성공 응답 반환
        return jsonify({
            "message": "처리 완료",
            "file_id": new_file_id,
            "translate_status": "success" if translate_success else "failed"
        })

    except Exception as e:
        logger.error(f"❌ [치명적 서버 에러]: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    finally:
        # 파일 정리 및 메모리 해제
        for f in files_to_clean:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
        gc.collect() # 마지막으로 메모리 비우기

@app.route('/api/chat', methods=['POST'])
def chat():
    # 1. 데이터 가져오기
    try:
        data = request.json
        user_input = data.get('message')
        file_id = data.get('file_id')
    except:
        return jsonify({'response': '잘못된 요청 형식입니다.'}), 400

    if not user_input: return jsonify({'response': '메시지가 없습니다.'}), 400
    if not file_id: return jsonify({'response': '파일 ID가 없습니다.'}), 400

    # 2. API 키 설정
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key: return jsonify({"error": "API Key 없음"}), 500

    genai.configure(api_key=api_key)

    # 3. DB 조회
    try:
        record = supabase.table('Files').select('extracted_text').eq('id', file_id).execute()
        if not record.data: return jsonify({'response': '파일 없음'}), 404

        file_text = record.data[0]['extracted_text'] or "내용 없음"
        truncated_text = file_text[:30000]  # 길이 제한

        # 4. [핵심] 사용 가능한 모델 자동 검색 (에러 방지용)
        valid_model_name = 'gemini-pro'  # 기본값
        try:
            print("--- 모델 찾는 중 ---")
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    # 'gemini'가 들어가는 모델 찾기
                    if 'gemini' in m.name:
                        valid_model_name = m.name
                        print(f"사용할 모델 발견: {valid_model_name}")
                        break
        except Exception as e:
            print(f"모델 목록 조회 실패 (기본값 사용): {e}")

        # 5. 프롬프트 합치기 (구버전 호환성 100%)
        # system_instruction 파라미터를 안 쓰고 직접 합칩니다.
        final_prompt = f"""
        [문서 내용]
        {truncated_text}

        [지시]
        위 내용을 바탕으로 아래 질문에 한국어로 답해줘.

        [질문]
        {user_input}
        """

        # 검색된 모델 이름으로 생성
        model = genai.GenerativeModel(valid_model_name)

        response = model.generate_content(final_prompt)
        return jsonify({'response': response.text})

    except Exception as e:
        print(f"Error Log: {e}")
        return jsonify({'response': f'오류 발생: {str(e)}'}), 500


@app.route('/api/viewDocument', methods=['GET'])
def views():
    user_id = request.args.get('user_id')
    try:
        response = supabase.table('Files').select('*')\
            .eq('user_id', user_id).order('created_at', desc=True).execute()
        return jsonify(response.data), 200
    except Exception as e:
        print(f'조회 오류: {e}')
        return jsonify({'error': '문서를 찾거나 조회할 수 없습니다.'}),400


@app.route('/api/viewMyDocument', methods=['GET'])
def view():
    id = request.args.get('id')
    user_id = request.args.get('user_id')

    try:
        response = supabase.table('Files').select('*') \
            .eq('id', id).eq('user_id', user_id).single().execute()
        return jsonify(response.data), 200
    except Exception as e:
        print(f'조회 오류: {e}')
        return jsonify({'error': '문서를 찾거나 조회할 수 없습니다.'}), 400


# app.py

@app.route('/api/delete/<file_id>', methods=['DELETE'])
def delete_document(file_id):
    # 1. 요청자 확인 (보안)
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({'error': '유저 ID가 필요합니다.'}), 400

    try:
        # 2. 삭제할 파일 정보 조회 (파일 경로를 알기 위해)
        response = supabase.table('Files').select('*').eq('id', file_id).single().execute()
        file_data = response.data

        # 파일이 없거나, 소유자가 다르면 거부
        if not file_data:
            return jsonify({'error': '파일을 찾을 수 없습니다.'}), 404

        if file_data['user_id'] != user_id:
            return jsonify({'error': '삭제 권한이 없습니다.'}), 403

        # 3. Supabase Storage에서 실제 파일 삭제 (용량 확보)
        # URL에서 스토리지 내부 경로(path)만 추출하는 로직
        # URL 예시: .../public/documents/originals/file.pdf -> originals/file.pdf 추출
        paths_to_remove = []
        bucket_name = 'documents'  # 사용 중인 버킷 이름 (STORAGE_BUCKET 변수 사용 권장)

        if file_data.get('original_url'):
            try:
                # URL에서 버킷 이름 뒷부분의 경로만 잘라냄
                path = file_data['original_url'].split(f"/public/{bucket_name}/")[-1]
                paths_to_remove.append(path)
            except:
                pass

        if file_data.get('translated_url'):
            try:
                path = file_data['translated_url'].split(f"/public/{bucket_name}/")[-1]
                paths_to_remove.append(path)
            except:
                pass

        if paths_to_remove:
            print(f"🗑️ 스토리지 파일 삭제 시도: {paths_to_remove}")
            supabase.storage.from_(bucket_name).remove(paths_to_remove)

        # 4. DB 테이블에서 데이터 삭제
        supabase.table('Files').delete().eq('id', file_id).execute()

        return jsonify({'message': '삭제 성공', 'id': file_id}), 200

    except Exception as e:
        print(f"❌ 삭제 중 오류: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
