import csv
from datetime import datetime

import boto3
import pandas as pd
import requests
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from pathlib import Path
from openai import OpenAI
import json
import time
import random
import set_client
import re
from pydantic import BaseModel, Field, ValidationError, field_validator
from typing import List, Optional
import os
from dotenv import load_dotenv

# 설정
current_file = Path(__file__).resolve()
BASE_DIR = current_file.parent.parent
LINKS_FILE = BASE_DIR / "data" / "msd_source" / "links.csv"
RAW_DATA_FILE = BASE_DIR / "data" / "msd_source" / "symptoms.csv"
EXTRACTED_DATA_FILE = BASE_DIR / "data" / "msd_source" / "silver_data.csv"

load_dotenv()
API_KEY=os.getenv('OPENROUTER_API_KEY')
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=API_KEY)

#######################################################################################
# minio 저장
def store(data, filepath="msd_raws/links.json"):
    # MinIO 연결
    bucket = 'silver'
    try:
        set_client.s3.head_bucket(Bucket=bucket)
    except:
        set_client.s3.create_bucket(Bucket=bucket)
    
    try:
        import json
        body = json.dumps(data, ensure_ascii=False, indent=4)
        
        set_client.s3.put_object(
            Bucket=bucket,
            Key=f"{filepath}",
            Body=body,
            ContentType='text/json'
        )
        
        print(f"[+] Success to save data in  MinIO({bucket}/{filepath})")
        return filepath

    except Exception as e:
        print(f"[!] Error processing: {e}")
####################################################################################
def html_cleaner(html):
    """
    제공된 topic-main-content 영역에서 불필요한 태그를 제거하고 
    AI가 읽기 좋은 순수 텍스트 구조로 변환합니다.
    """
    if not html:
        return ""

    # 1. 제거할 요소들 (표, 이미지 캡션 등 비정형 요소)
    for extra in html.find_all(['table', 'figure', 'script', 'style']):
        extra.decompose()

    # 2. 텍스트 추출 (줄바꿈 유지)
    text = html.get_text(separator="\n", strip=True)

    # 3. 정규표현식 클리닝
    # - 연속된 줄바꿈 제거
    text = re.sub(r'\n+', '\n', text)
    # - 의미 없는 특수문자나 중복 공백 제거
    text = re.sub(r'[ \t]+', ' ', text)
    
    return text.strip()

def extractor():
    if not LINKS_FILE.exists():
        print("links.csv 파일이 없습니다.")
        return
    
    # 1. URL 리스트를 메모리에 한 번만 로드
    if not LINKS_FILE.exists():
        return
    links_df = pd.read_csv(LINKS_FILE)
    
    # 2. 전체 개수 확인 (진행 상황 파악용)
    total_count = len(links_df)
    print(f"총 {total_count}개의 URL을 로드했습니다.")
    final_results = []
        
    for index, row in links_df.iterrows():
        
        symptom_name = row['SYMPTOM_NAME']
        url = row['URL']
        category = row['CATEGORY']
        base_symptom_id = f"S{str(index+1).zfill(3)}" # S001, S002...
        
        print(f"[{index + 1}/{total_count}] {row['SYMPTOM_NAME']} 처리 중...")
        
        try: # 웹페이지 요청
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            
            soup = BeautifulSoup(res.text, 'html.parser')
            main_content = soup.find('div', {'data-testid': 'topic-main-content'})
            if not main_content:
                log_fail_link(symptom_name, url, "Main content not found")
                continue
            clean_text = html_cleaner(main_content)
            
            max_retries = 3  # 최대 3번까지 다시 시도
            ai_response = None
            
            # [AI 호출 및 검증]
            for attempt in range(max_retries):
                ai_response = get_ai_answer(symptom_name, clean_text)
                
                if ai_response is not None:
                    break  # 성공하면 루프 탈출
                
                wait_time = (attempt + 1) * 5  # 실패 시 5초, 10초, 15초 대기
                print(f"    [!] 응답 빈 값 발생. {wait_time}초 후 재시도 중... ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)

            if ai_response is None:
                print(f"[{base_symptom_id}] {max_retries}번 시도했으나 결국 실패했습니다. 건너뜁니다.")
                log_fail_link(symptom_name, url, "Max retries exceeded with None response")
                continue
            
            ai_raw_response = get_ai_answer(symptom_name, clean_text)
            
            validated_response = validate_ai_response(ai_raw_response)
            if not validated_response:
                log_fail_link(symptom_name, url, "Schema validation failed")
                continue

            # ai_response가 확실히 dict일 때만 get을 호출
            extracted_list = validated_response.get('symptoms', [])
            
            if isinstance(extracted_list, list): # 응답이 리스트인 경우
                for sub_idx, item in enumerate(extracted_list):
                    # 하위 ID 부여 (예: S001-1, S001-2)
                    item['symptom_id'] = f"{base_symptom_id}-{sub_idx+1}"
                    item['name'] = symptom_name
                    item['category'] = category
                    final_results.append(item)
        
            # 증상별 원본 html 저장
            if (index+1) % 5 == 0:
                pd.DataFrame(final_results).to_csv(EXTRACTED_DATA_FILE, index=False, encoding='utf-8-sig')
                print(f"--- 중간 저장 완료 ({index+1}개) ---")
            
            time.sleep(random.uniform(5,10)) # 서버 부하 방지

        except Exception as e:
            print(f"에러 발생 ({symptom_name}): {e}")
            log_fail_link(symptom_name, url, str(e))
        
    final_df = pd.DataFrame(final_results)
    final_df.to_csv(EXTRACTED_DATA_FILE, index=False, encoding='utf-8-sig')
    

def get_ai_answer(symptom, content_text):
    try:
        response_text = None
        format = {"symptoms": [
            {"cause": "...", "is_red_flag": True, "context": "...", "warning_sign": "...", "action_guide": "...", "pre_exist_condition": "..." },
            { "cause": "...", "is_red_flag": False, "context": "...", "warning_sign": "...", "action_guide": "...", "pre_exist_condition": "..." }
        ]}
        
        prompt = f"""
        당신은 의료 데이터 전문가입니다.
        아래 의료 텍스트에서 정보를 추출하여 JSON 형식으로 답변하세요.
        아래의 규칙을 반드시 지키세요.
        
        [출력 형식]
        반드시 아래와 같은 구조의 JSON 배열로 응답하세요.
        {json.dumps(format, ensure_ascii=False)}
        
        
        [규칙]
        1. 출력 형식을 반드시 지키고, 오직 json object만 반환하세요.
        2. 텍스트를 분석하여 '일반적인 증상 관리 케이스'와 '즉시 의사 진료가 필요한 응급 케이스(Red Flag)'를 각각 별도의 객체로 분리하여 리스트에 담으세요.
        3. '경고 징후' 섹션의 내용은 반드시 is_red_flag: true인 객체에 포함시키세요.
        4. 만약 추출할 내용이 없다면 null을 사용하지 말고 반드시 빈 문자열 ""로 응답하세요.
        
        [Keys]
        - cause: 증상 발현 원인 / type: text
        - is_red_flag: 즉시 의사 방문 필요 여부. 증상이 보이기만 해도 병원에 방문해야 하는 경우. / type: bool
        - context: 증상 발현 상황. / type: text
        - warning_sign: 특별한 어떤 증상이 있을 경우 의사에게 방문을 권고하는 사항. / type: text
        - action_guide: 대응 권장사항 / type: text
        - pre_exist_condition: 관련된 기저질환 또는 특수상황 / type: text
        
        [텍스트]
        증상: {symptom}
        {content_text[:4500]}  # 토큰 제한 고려
        """
        
        response = client.chat.completions.create(
                        # model="meta-llama/llama-3.3-70b-instruct",
                        model="google/gemini-2.0-flash-001",
                        messages=[{"role": "system", "content": "YYou are a medical data extractor. You MUST respond ONLY with a valid JSON object. No conversation, no preamble."}, {"role": "user", "content": prompt}],
                        response_format={"type": "json_object"},
                        temperature=0.1 
                    )
        # 1. 응답 텍스트 추출 및 None 체크
        if not response.choices or not response.choices[0].message:
            print(f"[{symptom}] API 응답 구조가 올바르지 않습니다.")
            return None

        response_text = response.choices[0].message.content

        # 핵심 수정: response_text가 None이거나 문자열이 아닌 경우를 완벽 차단
        if response_text is None or not isinstance(response_text, str):
            print(f"[{symptom}] AI 응답 내용이 비어있습니다 (NoneType).")
            return None
        
        raw_content = json.loads(response_text)
        
        if isinstance(raw_content, dict):
            # 'symptoms' 키가 없는 경우 빈 리스트라도 넣어 리턴
            if 'symptoms' not in raw_content:
                raw_content['symptoms'] = []
            return raw_content
    
        # 2. 응답이 문자열(str)인 경우
        if isinstance(raw_content, str):
            clean_content = raw_content.strip()
            if not clean_content:
                print(f"[{symptom}] AI 응답이 빈 문자열입니다.")
                return None
            return json.loads(clean_content)
            
        return None

    except json.JSONDecodeError as e:
        try:
            # 2. 정규표현식으로 가장 바깥쪽 { } 내용을 찾음
            # [ \s\S]*? 는 줄바꿈을 포함한 모든 문자를 의미
            match = re.search(r'(\{.*\}|\[.*\])', response_text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        except Exception as e:
            print(f"[{symptom}] JSON 파싱 실패: {e}")
            return None
    except Exception as e:
        print(f"[{symptom}] AI 호출 중 일반 오류: {e}")
        return None
    except Exception as e:
        print(f"AI 추출 오류: {e}")
        return None

####################################################################
# ai 답변 검증
class SymptomItem(BaseModel):
    cause: str = Field(..., description="증상 발현 원인")
    is_red_flag: bool = Field(..., description="응급 여부")
    context: str = Field(..., description="증상 발현 상황")
    warning_sign: Optional[str] = Field(default="", description="경고 징후")
    action_guide: str = Field(..., description="대응 가이드")
    pre_exist_condition: str = Field(..., description="기저질환")
    
    @field_validator('warning_sign', 'pre_exist_condition', mode='before')
    @classmethod
    def prevent_none(cls, v):
        return v if v is not None else ""

class AIResponseSchema(BaseModel):
    symptoms: List[SymptomItem]

def validate_ai_response(raw_json):
    """AI 응답 형식을 검증합니다."""
    try:
        validated_data = AIResponseSchema(**raw_json)
        return validated_data.model_dump()
    except ValidationError as e:
        print(f"스키마 검증 실패: {e.json()}")
        return None

#####################################################################################
# 실패한 증상 저장
def log_fail_link(symptom_name, url, error_msg):
    """실패한 링크를 csv에 기록합니다."""
    fail_file = 'fail_links.csv'
    file_exists = os.path.isfile(fail_file)
    with open(fail_file, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['SYMPTOM_NAME', 'URL', 'ERROR_MESSAGE', 'TIMESTAMP'])
        writer.writerow([symptom_name, url, error_msg, datetime.now()])
    
if __name__=='__main__':
    extractor()