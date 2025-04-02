import streamlit as st
import asyncio
import os
import tempfile
from pyzerox import zerox
from pyzerox.core.types import ZeroxOutput
import pyperclip # 클립보드 복사 기능
from pathlib import Path # 파일 확장자 얻기 위해

# --- 기본 프롬프트 정의 ---
DEFAULT_SYSTEM_PROMPT = """
파일에 있는 텍스트만 출력하세요.
파일에서 텍스트를 추출하고 마크다운 형식으로 변환해주세요.
표와 구조를 최대한 유지해주세요.
페이지 번호가 나와있다면 내용의 가장 마지막에 {p.#}의 형태로 페이지 번호를 함께 제시해주세요.
"""

# --- Streamlit Secrets에서 API 키 확인 및 설정 ---
openai_api_key = st.secrets.get("OPENAI_API_KEY")

if not openai_api_key:
    st.error("오류: Streamlit Secrets에 OPENAI_API_KEY가 설정되지 않았습니다.")
    st.info("앱을 실행하기 전에 `.streamlit/secrets.toml` 파일 또는 Streamlit Cloud의 Secrets 설정을 통해 API 키를 추가해주세요.")
    st.stop() # API 키 없으면 앱 실행 중지
else:
    # zerox 라이브러리가 환경 변수를 사용하도록 설정
    os.environ["OPENAI_API_KEY"] = openai_api_key

# --- 세션 상태 초기화 ---
if 'ocr_result' not in st.session_state:
    st.session_state.ocr_result = None
if 'extracted_text' not in st.session_state:
    st.session_state.extracted_text = ""
if 'processing_done' not in st.session_state:
    st.session_state.processing_done = False

# --- 앱 UI 구성 ---
st.title("ZeroX OCR 텍스트 추출 앱 (gpt-4o)")
st.write("PDF 또는 이미지 파일에서 텍스트를 추출합니다. API 키는 Streamlit Secrets를 통해 관리됩니다.")

# 파일 업로드 위젯 (PDF 및 이미지 지원)
uploaded_file = st.file_uploader(
    "텍스트를 추출할 PDF 또는 이미지 파일을 업로드하세요",
    type=["pdf", "png", "jpg", "jpeg", "bmp", "webp"]
)

# 페이지 선택 옵션 (PDF인 경우에만 표시)
select_pages = None
page_option = None
if uploaded_file is not None and uploaded_file.type == "application/pdf":
    page_option = st.radio(
        "처리할 페이지를 선택하세요:",
        ["모든 페이지", "특정 페이지"],
        key="page_option_radio" # 키를 지정하여 상태 유지
    )
    if page_option == "특정 페이지":
        page_input = st.text_input("페이지 번호를 입력하세요 (예: 1,3,5)", key="page_input_text")
        if page_input:
            try:
                # 입력된 문자열에서 숫자만 추출하여 리스트 생성
                select_pages = [int(p.strip()) for p in page_input.split(",") if p.strip().isdigit()]
                if not select_pages: # 유효한 숫자가 없는 경우
                    st.warning("유효한 페이지 번호가 없습니다. 페이지 번호는 숫자로 입력해주세요.")
            except ValueError: # int 변환 실패 시 (사실 isdigit()으로 거의 걸러짐)
                st.error("숫자와 쉼표(,)만 사용하여 페이지 번호를 입력하세요.")

# --- 실행 로직 ---
if uploaded_file is not None and st.button("텍스트 추출 시작", key="start_button"):
    # 이전 결과 초기화
    st.session_state.ocr_result = None
    st.session_state.extracted_text = ""
    st.session_state.processing_done = False

    # 페이지 번호 유효성 검사 (특정 페이지 선택 시)
    is_valid_page_selection = True
    if page_option == "특정 페이지":
        if not select_pages: # 유효한 페이지 번호가 입력되지 않았거나, 숫자 아닌 값이 포함된 경우
            st.warning("유효한 특정 페이지 번호가 입력되지 않았습니다. 모든 페이지를 처리합니다.")
            select_pages = None # 모든 페이지 처리로 전환
            is_valid_page_selection = False # 사용자에게 알림 용도 (선택적)

    with st.spinner("텍스트 추출 중... 잠시만 기다려주세요."):
        # 임시 파일로 저장 (원본 파일 확장자 유지 시도)
        file_extension = Path(uploaded_file.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            file_path = tmp_file.name

        # 비동기 함수 정의
        async def process_file_async(f_path, s_pages):
            try:
                # pyzerox 호출 (모델 고정, 프롬프트 고정)
                result: ZeroxOutput = await zerox(
                    file_path=f_path,
                    model="gpt-4o", # 모델 고정
                    output_dir="./output", # 필요시 결과 저장 경로
                    custom_system_prompt=DEFAULT_SYSTEM_PROMPT, # 고정된 기본 프롬프트 사용
                    select_pages=s_pages
                )
                return result
            except Exception as e:
                st.error(f"ZeroX 처리 중 오류 발생: {e}")
                return None
            finally:
                # 임시 파일 확실히 삭제
                try:
                    if os.path.exists(f_path):
                        os.unlink(f_path)
                        # print(f"임시 파일 삭제: {f_path}") # 디버깅용
                except Exception as e_unlink:
                    st.warning(f"임시 파일 삭제 중 오류 발생: {e_unlink}")

        # 비동기 함수 실행 및 결과 저장
        try:
            # asyncio.run 사용 (더 간결)
            result = asyncio.run(process_file_async(file_path, select_pages))

            if result and isinstance(result, ZeroxOutput):
                st.session_state.ocr_result = result
                # 전체 텍스트 생성 (마크다운 형식)
                all_text_parts = []
                if len(result.pages) > 1: # 여러 페이지 결과 (주로 PDF)
                    for page in result.pages:
                        all_text_parts.append(f"## 페이지 {page.page}\n\n{page.content}")
                elif result.pages : # 단일 페이지 (이미지 또는 단일 페이지 PDF)
                    all_text_parts.append(result.pages[0].content)
                else: # 결과 페이지가 없는 경우
                    all_text_parts.append("추출된 텍스트가 없습니다.")

                st.session_state.extracted_text = "\n\n".join(all_text_parts)
                st.session_state.processing_done = True
                st.success(f"텍스트 추출 완료! 처리 시간: {result.completion_time:.2f}ms")

            elif result is None:
                # 오류는 process_file_async 내에서 st.error로 표시됨
                st.warning("텍스트 추출에 실패했습니다.")
            else: # 예상치 못한 결과 타입
                st.error(f"예상치 못한 결과 타입: {type(result)}")

        except Exception as e:
            st.error(f"전체 처리 중 오류가 발생했습니다: {str(e)}")
            # 임시 파일 삭제 시도 (오류 발생 시에도)
            try:
                if 'file_path' in locals() and os.path.exists(file_path):
                    os.unlink(file_path)
                    # print(f"오류 발생 후 임시 파일 삭제: {file_path}") # 디버깅용
            except Exception as e_unlink:
                st.warning(f"오류 발생 후 임시 파일 삭제 중 오류: {e_unlink}")

# --- 결과 표시 및 상호작용 ---
if st.session_state.processing_done and st.session_state.extracted_text:
    st.markdown("---")
    st.subheader("📄 추출된 텍스트 결과")

    # 결과 텍스트 영역 (스크롤 가능하게)
    st.text_area("결과", st.session_state.extracted_text, height=300, key="result_text_area", disabled=True)

    col1, col2, col3 = st.columns([1, 1, 2]) # 버튼 배치를 위한 컬럼

    with col1:
        # 복사 버튼
        if st.button("📋 텍스트 복사 및 지우기", key="copy_clear_button"):
            try:
                pyperclip.copy(st.session_state.extracted_text)
                st.success("텍스트가 클립보드에 복사되었습니다! 결과가 지워집니다.")
                # 결과 상태 초기화
                st.session_state.ocr_result = None
                st.session_state.extracted_text = ""
                st.session_state.processing_done = False
                # 페이지 새로고침 효과 (결과 즉시 지우기 위해 rerun)
                st.rerun()
            except pyperclip.PyperclipException as e:
                st.error(f"클립보드 접근 오류: {e}. 'pyperclip' 라이브러리가 시스템 환경에서 작동하는지 확인하세요.")
            except Exception as e:
                st.error(f"클립보드 복사/지우기 중 오류 발생: {e}")

    with col2:
        # 다운로드 버튼 (옵션)
        if st.session_state.ocr_result:
            # 파일 이름 생성 시 원본 파일 이름 사용 시도
            original_filename_stem = Path(uploaded_file.name).stem if uploaded_file else Path(st.session_state.ocr_result.file_name).stem
            download_filename = f"{original_filename_stem}_extracted.md"

            st.download_button(
                label="💾 결과 다운로드 (.md)",
                data=st.session_state.extracted_text,
                file_name=download_filename,
                mime="text/markdown",
                key="download_button"
            )

    st.markdown("---")
    # 원본 데이터 표시 (Expander 사용)
    if st.session_state.ocr_result:
        with st.expander("📊 처리 정보 보기 (JSON)"):
            try:
                st.json({
                    "completion_time_ms": st.session_state.ocr_result.completion_time,
                    "file_name_processed": st.session_state.ocr_result.file_name, # zerox가 반환한 파일 경로
                    "input_tokens": st.session_state.ocr_result.input_tokens,
                    "output_tokens": st.session_state.ocr_result.output_tokens,
                    "pages_info": [{"page": p.page, "content_length": p.content_length} for p in st.session_state.ocr_result.pages]
                })
            except Exception as e:
                st.error(f"처리 정보 표시에 오류가 발생했습니다: {e}")

# --- 사용 방법 안내 ---
st.markdown("---")
with st.expander("💡 사용 방법"):
    st.markdown("""
    1.  **API 키 설정:** (최초 1회)
        *   **로컬:** 프로젝트 폴더 내 `.streamlit/secrets.toml` 파일에 `OPENAI_API_KEY = "sk-..."` 형식으로 키를 저장합니다.
        *   **배포:** Streamlit Cloud 앱 설정의 Secrets 메뉴에서 `OPENAI_API_KEY` 이름으로 키 값을 추가합니다.
    2.  **파일 업로드:** 'Browse files' 버튼을 클릭하여 텍스트를 추출할 PDF 또는 이미지(PNG, JPG 등) 파일을 선택합니다.
    3.  **(PDF만 해당) 페이지 선택:** PDF 파일을 업로드한 경우, 모든 페이지를 처리할지 특정 페이지만 처리할지 선택합니다. 특정 페이지 선택 시 페이지 번호를 쉼표로 구분하여 입력합니다 (예: 1, 3, 5). 잘못된 값이 입력되면 모든 페이지가 처리됩니다.
    4.  **추출 시작:** '텍스트 추출 시작' 버튼을 클릭합니다.
    5.  **결과 확인:** 잠시 기다리면 추출된 텍스트가 아래 텍스트 상자에 나타납니다.
    6.  **복사 및 지우기:** '텍스트 복사 및 지우기' 버튼을 클릭하면 결과가 클립보드에 복사되고 화면의 결과는 지워져 다음 파일을 처리할 준비가 됩니다.
    7.  **(선택) 다운로드:** '결과 다운로드 (.md)' 버튼을 클릭하여 추출된 텍스트를 마크다운 파일로 저장할 수 있습니다.
    """)

# 주의사항 (메인 페이지 하단으로 이동)
st.info("""
**참고:**
- 처리 시간은 파일 크기, 페이지 수, 이미지 복잡도 및 네트워크 상태에 따라 달라질 수 있습니다.
- OpenAI API 사용량에 따라 비용이 발생합니다.
- 이미지 파일의 경우, 페이지 개념이 없으므로 전체 이미지를 단일 페이지로 처리합니다.
- PDF 처리를 위해서는 시스템에 `poppler` 유틸리티가 설치되어 있어야 할 수 있습니다. (Linux: `sudo apt-get install poppler-utils`, macOS: `brew install poppler`, Windows: poppler 바이너리 다운로드 및 PATH 설정)
""")
