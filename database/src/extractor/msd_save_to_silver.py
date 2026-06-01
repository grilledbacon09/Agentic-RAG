# html에서 텍스트 추출
from datetime import datetime
import json
import random
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import pandas as pd
import re

import set_client

# 설정
current_file = Path(__file__).resolve()
BASE_DIR = current_file.parent.parent
LINKS_FILE = BASE_DIR / "data" / "msd_source" / "links.csv"

# 섹션 추출을 위한 헬퍼 함수
# 헬퍼 함수 A: TopicFHead (원인, 요점 등 큰 섹션)
def get_fhead_content(soup, keywords):
    headings = soup.find_all(attrs={'data-testid': 'topicFHeadHeading'})
    
    for heading in headings:
        if any(k in heading.get_text() for k in keywords):
            # heading이 포함된 상위 section을 찾고, 그 내부의 body div를 찾습니다.
            parent_section = heading.find_parent('section')
            if parent_section:
                # 클래스명 뒤의 난수가 바뀌어도 찾을 수 있게 정규표현식 사용
                body = parent_section.find('div', class_=re.compile(r'TopicFHead_fHeadBody'))
                if body:
                    text = body.get_text(separator="\n", strip=True)
                    return re.sub(r'\n+', '\n', text)
    return ""

# 헬퍼 함수 B: TopicHHead (경고 징후, 의사의 진찰 등 하위 섹션)
def get_hhead_content(soup, keywords):
    # data-testid가 topicHHead인 모든 section을 찾습니다.
    sections = soup.find_all('section', attrs={'data-testid': 'topicHHead'})
    
    for section in sections:
        # 섹션 내의 h3 타이틀 텍스트 확인
        header = section.find('h3')
        if header and any(k in header.get_text() for k in keywords):
            # h3와 형제 관계인 내용을 담은 div를 찾습니다.
            # 보통 h3 다음에 바로 오는 div 안에 내용이 있습니다.
            content_div = header.find_next_sibling('div')
            if content_div:
                text = content_div.get_text(separator="\n", strip=True)
                return re.sub(r'\n+', '\n', text)
    return ""

# 증상 / 경고징후 / 의사의 진찰이 필요한 경우 / 특수상황, 기저질환 추출
def extract_sections(html_content, symptom_id, category):
    soup = BeautifulSoup(html_content, 'lxml')
    
    # 1. name: 질환명 (h1)
    h1_tag = soup.find('h1')
    name = h1_tag.get_text(strip=True) if h1_tag else "Unknown"
    synonym_tag = soup.find(attrs={'data-testid':'topicSynonym'})
    synonym = f" ({synonym_tag.get_text(strip=True)})" if synonym_tag else ""
    full_symptom_name = name + synonym

    # 2. 각 섹션별 데이터 매핑
    cause = get_fhead_content(soup, [f"{name}의 원인", "원인", "발생 원인"])
    key_points = get_fhead_content(soup, ["요점", "핵심점"])
    
    if not key_points:
        intro_div = soup.find('div', attrs={"data-testid": "topic-main-content"})
        if intro_div:
            intro_texts = []
            for child in intro_div.children:
                if child.name == 'section': break
                if child.name == 'p':
                    intro_texts.append(child.get_text(strip=True))
            key_points = " ".join(intro_texts)

    warning_sign = get_hhead_content(soup, ["경고 징후", "경고 증상"])
    meet_doc = get_hhead_content(soup, ["의사의 진찰이 필요한 경우", "의사를 만나야 하는 경우"])
    action_guide = get_hhead_content(soup, ["치료", "관리", "위생"])

    is_red_flag = True if ("즉시" in meet_doc and "병원에 방문해야" in meet_doc) else False
    
    res = {
        "symptom_id": symptom_id,
        "name": full_symptom_name,
        "category": category,
        "is_red_flag": is_red_flag,
        "cause": cause,
        "warning_sign": warning_sign,
        "meet_doc": meet_doc,
        "action_guide": action_guide,
        "pre_exist_condition": key_points
    }
    return res

# def msd_extraction():
#     BUCKET = "bronze"
#     PREFIX = "msd_raw"
    
#     try:
#         conn = set_client.get_db_conn()
#         cur = conn.cursor()
        
#         response = set_client.s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX+'/')
#         if 'Contents' not in response: return

#         for obj in response['Contents']:
#             file_key = obj['Key']
#             if not file_key.endswith('.html'): continue
            
#             print(f"[*] Extracting Raw Data: {file_key}")
#             file_obj = set_client.s3.get_object(Bucket=BUCKET, Key=file_key)
#             html_content = file_obj['Body'].read().decode('utf-8')
            
#             raw_data = extract_sections(html_content)
            
#             # DB 적재 (Silver 초기 단계)
#             upsert_query = """
#                 INSERT INTO silver_symptom 
#                 (name, warning_sign, meet_doc, pre_exist_condition, source_file)
#                 VALUES (%s, %s, %s, %s, %s)
#                 ON CONFLICT (name) DO UPDATE SET
#                     warning_sign = EXCLUDED.warning_sign,
#                     meet_doc = EXCLUDED.meet_doc,
#                     pre_exist_condition = EXCLUDED.pre_exist_condition;
#             """
#             cur.execute(upsert_query, (
#                 raw_data['name'], raw_data['warning_sign'], 
#                 raw_data['meet_doc'], raw_data['pre_exist_condition'], file_key
#             ))

#         conn.commit()
#         print("[+] Silver Raw Extraction 완료.")
        
#     except Exception as e:
#         print(f"[!] 에러: {e}")
#     finally:
#         if conn:
#             cur.close()
#             conn.close()
            
# def save_results_to_json(data_list, base_filename="symptom"):
#     """
#     추출된 리스트를 JSON 파일로 저장하고 MinIO로 전송합니다.
#     """
#     timestamp = datetime.now().strftime('%Y%m%d')
#     local_file = f"{base_filename}_{timestamp}.json"
    
#     # 1. 로컬에 JSON 파일로 저장 (utf-8-sig로 한글 깨짐 방지)
#     with open(local_file, 'w', encoding='utf-8-sig') as f:
#         json.dump(data_list, f, ensure_ascii=False, indent=4)
#     print(f"[+] 로컬 저장 완료: {local_file}")

#     # 2. MinIO(S3)에 업로드 (선택 사항)
#     try:
#         import set_client
#         bucket_name = "silver" # 정제된 데이터이므로 silver zone
#         file_key = f"symptoms/{local_file}"
        
#         # 가공된 dict를 바로 JSON 문자열로 변환하여 전송
#         json_body = json.dumps(data_list, ensure_ascii=False, indent=4)
        
#         set_client.s3.put_object(
#             Bucket=bucket_name,
#             Key=file_key,
#             Body=json_body,
#             ContentType='application/json'
#         )
#         print(f"[+] MinIO 업로드 완료: {bucket_name}/{file_key}")
#     except Exception as e:
#         print(f"[!] MinIO 업로드 실패: {e}")

def save_results_to_db(data_list: list[dict]):
    """
    추출된 결과를 PostgreSQL silver_symptom 테이블에 upsert합니다.
    """
    upsert_query = """
        INSERT INTO silver_symptom 
            (symptom_id, name, category, is_red_flag,
             cause, warning_sign, meet_doc, action_guide,
             pre_exist_condition, updated_at)
        VALUES 
            (%(symptom_id)s, %(name)s, %(category)s, %(is_red_flag)s,
             %(cause)s, %(warning_sign)s, %(meet_doc)s, %(action_guide)s,
             %(pre_exist_condition)s, NOW())
        ON CONFLICT (symptom_id) DO UPDATE SET
            name                = EXCLUDED.name,
            category            = EXCLUDED.category,
            is_red_flag         = EXCLUDED.is_red_flag,
            cause               = EXCLUDED.cause,
            warning_sign        = EXCLUDED.warning_sign,
            meet_doc            = EXCLUDED.meet_doc,
            action_guide        = EXCLUDED.action_guide,
            pre_exist_condition = EXCLUDED.pre_exist_condition,
            updated_at          = NOW();
    """
    conn = None
    try:
        conn = set_client.get_db_conn()
        cur = conn.cursor()
        cur.executemany(upsert_query, data_list)  # 배치 처리
        conn.commit()
        print(f"[+] PostgreSQL 저장 완료: {len(data_list)}건")
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[!] DB 저장 실패: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()


if __name__ == "__main__":
    if not LINKS_FILE.exists():
        print(f"파일을 찾을 수 없습니다: {LINKS_FILE}")
    else:
        links_df = pd.read_csv(LINKS_FILE)
        total_count = len(links_df)
        print(f"총 {total_count}개의 URL 처리를 시작합니다.")
        
        final_results = []
        headers = {'User-Agent': 'Mozilla/5.0'}

        for index, row in links_df.iterrows():
            symptom_id = f"S{str(index+1).zfill(3)}"
            print(f"[{index+1}/{total_count}] {row['SYMPTOM_NAME']} 처리 중...")
            
            try:
                res = requests.get(row['URL'], headers=headers, timeout=10)
                res.raise_for_status()
                
                # 데이터 추출
                extracted_data = extract_sections(res.text, symptom_id, row['CATEGORY'])
                if index < 3:
                    print(extracted_data)
                final_results.append(extracted_data)
                
                # 서버 부하 방지
                time.sleep(random.uniform(1.0, 2.0))
                
            except Exception as e:
                print(f"   [!] 에러 발생 ({row['SYMPTOM_NAME']}): {e}")

        # 최종 저장
        save_results_to_db(final_results)