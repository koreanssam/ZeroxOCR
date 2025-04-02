import streamlit as st
import asyncio
import os
import tempfile
from pyzerox import zerox
from pyzerox.core.types import ZeroxOutput
import pyperclip
from pathlib import Path
import base64
from io import BytesIO
from mimetypes import guess_type

# --- Langchain 관련 임포트 ---
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    from langchain_core.output_parsers import StrOutputParser
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    st.warning("Langchain 관련 라이브러리가 설치되지 않았습니다. 이미지 직접 처리가 제한될 수 있습니다.")
    st.warning("pip install langchain langchain-openai")

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
    st.stop()
else:
    os.environ["OPENAI_API_KEY"] = openai_api_key

# --- 세션 상태 초기화 ---
if 'ocr_result' not in st.session_state:
    st.session_state.ocr_result = None
if 'extracted_text' not in st.session_state:
    st.session_state.extracted_text = ""
if 'processing_done' not in st.session_state:
    st.session_state.processing_done = False
if 'last_processed_type' not in st.session_state:
    st.session_state.last_processed_type = None

# --- 앱 UI 구성 ---
st.title("Koreanssam OCR")
st.write("PDF 또는 이미지 파일에서 텍스트를 추출합니다. API 키는 Streamlit Secrets를 통해 관리됩니다.")

uploaded_file = st.file_uploader(
    "텍스트를 추출할 PDF 또는 이미지 파일을 업로드하세요",
    type=["pdf", "png", "jpg", "jpeg", "bmp", "webp"]
)

select_pages = None
page_option = None
if uploaded_file is not None and uploaded_file.type == "application/pdf":
    page_option = st.radio(
        "처리할 페이지를 선택하세요:",
        ["모든 페이지", "특정 페이지"],
        key="page_option_radio"
    )
    if page_option == "특정 페이지":
        page_input = st.text_input("페이지 번호를 입력하세요 (예: 1,3,5)", key="page_input_text")
        if page_input:
            try:
                select_pages = [int(p.strip()) for p in page_input.split(",") if p.strip().isdigit()]
                if not select_pages:
                    st.warning("유효한 페이지 번호가 없습니다. 페이지 번호는 숫자로 입력해주세요.")
            except ValueError:
                st.error("숫자와 쉼표(,)만 사용하여 페이지 번호를 입력하세요.")

# --- 실행 로직 ---
if uploaded_file is not None and st.button("텍스트 추출 시작", key="start_button"):
    st.session_state.ocr_result = None
    st.session_state.extracted_text = ""
    st.session_state.processing_done = False
    st.session_state.last_processed_type = None

    file_type = uploaded_file.type
    st.write(f"감지된 파일 타입: {file_type}")

    with st.spinner("텍스트 추출 중... 잠시만 기다려주세요."):
        if file_type == "application/pdf":
            st.session_state.last_processed_type = 'pdf'
            is_valid_page_selection = True
            if page_option == "특정 페이지" and not select_pages:
                st.warning("유효한 특정 페이지 번호가 입력되지 않았습니다. 모든 페이지를 처리합니다.")
                select_pages = None

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(uploaded_file.getbuffer())
                file_path = tmp_file.name

            async def process_pdf_async(f_path, s_pages):
                try:
                    result: ZeroxOutput = await zerox(
                        file_path=f_path, model="gpt-4o",
                        output_dir="./output", custom_system_prompt=DEFAULT_SYSTEM_PROMPT,
                        select_pages=s_pages
                    )
                    return result
                except Exception as e:
                    st.error(f"ZeroX (PDF) 처리 중 오류 발생: {e}")
                    import traceback
                    st.text_area("Traceback (PDF)", traceback.format_exc(), height=150)
                    return None
                finally:
                    if os.path.exists(f_path): os.unlink(f_path)

            try:
                result = asyncio.run(process_pdf_async(file_path, select_pages))
                if result and isinstance(result, ZeroxOutput):
                    st.session_state.ocr_result = result
                    all_text_parts = []
                    if len(result.pages) > 1:
                        for page in result.pages: all_text_parts.append(f"## 페이지 {page.page}\n\n{page.content}")
                    elif result.pages: all_text_parts.append(result.pages[0].content)
                    else: all_text_parts.append("추출된 텍스트가 없습니다 (PDF).")
                    st.session_state.extracted_text = "\n\n".join(all_text_parts)
                    st.session_state.processing_done = True
                    st.success(f"PDF 텍스트 추출 완료! 처리 시간: {result.completion_time:.2f}ms")
                else:
                    st.warning("PDF 텍스트 추출에 실패했습니다.")
            except Exception as e:
                st.error(f"PDF 처리 전체 과정 중 오류 발생: {str(e)}")
                import traceback
                st.text_area("Traceback (PDF Async)", traceback.format_exc(), height=150)

        elif file_type.startswith("image/") and LANGCHAIN_AVAILABLE:
            st.session_state.last_processed_type = 'image'
            try:
                image_bytes = uploaded_file.getvalue()
                base64_image = base64.b64encode(image_bytes).decode("utf-8")
                mime_type = guess_type(uploaded_file.name)[0] or file_type
                image_url = f"data:{mime_type};base64,{base64_image}"

                llm = ChatOpenAI(model="gpt-4o", api_key=openai_api_key, max_tokens=4000)
                message = HumanMessage(content=[
                    {"type": "text", "text": DEFAULT_SYSTEM_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ])
                chain = llm | StrOutputParser()
                response_text = chain.invoke([message])

                st.session_state.extracted_text = response_text
                st.session_state.processing_done = True
                st.success("이미지 텍스트 추출 완료!")

            except Exception as e:
                st.error(f"이미지 처리 중 오류 발생: {str(e)}")
                import traceback
                st.text_area("Traceback (Image)", traceback.format_exc(), height=150)

        else:
            if file_type.startswith("image/") and not LANGCHAIN_AVAILABLE:
                st.error("이미지를 처리하려면 Langchain 라이브러리가 필요합니다. 설치 후 다시 시도해주세요.")
            else:
                st.error(f"지원하지 않는 파일 타입입니다: {file_type}. PDF 또는 이미지를 업로드해주세요.")

# --- 결과 표시 및 상호작용 (약간 수정) ---
if st.session_state.processing_done and st.session_state.extracted_text:
    st.markdown("---")
    st.subheader("📄 추출된 텍스트 결과")

    # 결과 텍스트 영역 (스크롤 가능하게)
    st.text_area("결과", st.session_state.extracted_text, height=300, key="result_text_area", disabled=True)

    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("📋 텍스트 복사 및 지우기", key="copy_clear_button"):
            try:
                pyperclip.copy(st.session_state.extracted_text)
                st.success("텍스트가 클립보드에 복사되었습니다! 결과가 지워집니다.")
                st.session_state.ocr_result = None
                st.session_state.extracted_text = ""
                st.session_state.processing_done = False
                st.session_state.last_processed_type = None
                st.rerun()
            except Exception as e:
                st.error(f"클립보드 작업 중 오류 발생: {e}")

    with col2:
        download_filename = "extracted_text.txt"
        if st.session_state.last_processed_type == 'pdf' and st.session_state.ocr_result:
            original_filename_stem = Path(st.session_state.ocr_result.file_name).stem
            download_filename = f"{original_filename_stem}_extracted.md"
            mime_type = "text/markdown"
        elif st.session_state.last_processed_type == 'image' and uploaded_file:
            original_filename_stem = Path(uploaded_file.name).stem
            download_filename = f"{original_filename_stem}_extracted.txt"
            mime_type = "text/plain"
        else:
            mime_type = "text/plain"

        st.download_button(
            label="💾 결과 다운로드",
            data=st.session_state.extracted_text,
            file_name=download_filename,
            mime=mime_type,
            key="download_button"
        )
