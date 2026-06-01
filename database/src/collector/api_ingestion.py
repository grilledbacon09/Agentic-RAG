import os
import json
import requests
import set_client
import math
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# API 설정
API_CONFIG = [
    {
        "name": "drug_info",
        "url": "https://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList",
        "params": {"serviceKey": os.getenv("API_KEY_1"), "type": "json", "numOfRows": 100}
    },
    # {
    #     "name": "taboo_info",
    #     "url": "https://apis.data.go.kr/1471000/DURPrdlstInfoService03/getUsjntTabooInfoList03",
    #     "params": {"serviceKey": os.getenv("API_KEY_2"), "type": "json", "numOfRows": 100}
    # }
]

def ingest_api(api_info):
    api_name = api_info['name']
    base_url = api_info['url']
    base_params = api_info['params'].copy()
    
    all_items = []
    page_no = 1
    total_count = 0
    max_retries = 5  # 502 에러 시 재시도 횟수
    
    print(f"[*] Starting full ingestion: {api_name}")
    
    while True:
        # 페이지네이션 파라미터 업데이트
        base_params['pageNo'] = page_no
        success = False
        
        for attempt in range(max_retries):
            try:
                response = requests.get(base_url, params=base_params, timeout=30)
                
                # 502, 503, 504 등 서버 에러 시 예외 발생
                response.raise_for_status() 
                
                data = response.json()
                body = data.get('body', {})
                items = body.get('items', [])
                total_count = body.get('totalCount', 0)

                if items:
                    all_items.extend(items)
                
                total_pages = math.ceil(total_count / base_params['numOfRows']) if total_count > 0 else "?"
                print(f"    -> Progress: Page {page_no}/{total_pages} ({len(all_items)}/{total_count} items collected)")
                
                success = True
                break # 성공 시 retry loop 탈출

            except Exception as e:
                print(f"    [!] Attempt {attempt + 1} failed for page {page_no}: {e}")
                time.sleep(2 ** attempt) # 지수 백오프 (2초, 4초, 8초 대기)
        
        # 재시도 끝에 실패했거나 더 이상 데이터가 없는 경우
        if not success:
            print(f"[!] Error ingesting {api_name} at page {page_no}: {e}")
            break
        
        if len(all_items) >= total_count or not items:
            break
        
        page_no += 1
        
    # 데이터가 1건이라도 있으면 저장 진행
    if all_items:
        save_to_bronze(api_name, all_items) # 저장 로직은 별도 함수로 분리 권장
    else:
        print(f"[!] No data collected for {api_name}.")

# Bronze Zone(MinIO) 저장 - 전체 데이터를 하나의 파일로 저장하거나, 페이지별 저장 가능
def save_to_bronze(api_name, items):
    try:
        # 전체 수집 데이터를 하나의 리스트로 감싸 저장
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_key = f"{api_name}/{timestamp}.json"
        bucket_name = "bronze"
        
        storage_data = {
            "metadata": {
                "api_name": api_name,
                "collected_at": timestamp,
                "total_count": len(items)
            },
            "items": items
        }
        
        set_client.s3.put_object(
            Bucket=bucket_name,
            Key=file_key,
            Body=json.dumps(storage_data, ensure_ascii=False)
        )
        
        # Metadata 기록(PostgreSQL)
        conn = set_client.get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO bronze_metadata (api_name, file_path, status, ingested_at) VALUES (%s, %s, %s, %s)",
            (api_name, file_key, "SUCCESS", datetime.now())
        )
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"[+] Successfully ingested ALL {len(items)} records for {api_name}")

    except Exception as e:
        # 실패 로그 기록
        try:
            conn = set_client.get_db_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO bronze_metadata (api_name, status, error_msg, ingested_at) VALUES (%s, %s, %s, %s)",
                (api_name, "FAILED", str(e), datetime.now())
            )
            conn.commit()
            cur.close()
            conn.close()
        except:
            pass

if __name__ == "__main__":
    # 버킷 생성 확인
    try:
        set_client.s3.create_bucket(Bucket='bronze')
    except:
        pass

    for api in API_CONFIG:
        ingest_api(api)