import requests
import boto3
import os
from dotenv import load_dotenv
from urllib.parse import unquote

load_dotenv()
# 식품의약품안전처_의약품안전사용서비스(DUR)품목정보
dur_url = "https://apis.data.go.kr/1471000/DURPrdlstInfoService03"
# 식품의약품안전처_의약품 제품 허가정보
approved_drug_url = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07"
# 	식품의약품안전처_의약품개요정보(e약은요)
drug_info_url = "https://apis.data.go.kr/1471000/DrbEasyDrugInfoService"

urls = {dur_url: "dur_data.json",
        approved_drug_url: "approved_drug_data.json",
        drug_info_url: "drug_info_data.json"}
api_key = os.getenv('PUBLIC_DATA_API_KEY')

# 1. api collect
def fetch_data(url):
    params = {
        'serviceKey': api_key,
        'type': 'json',
        'numOfRows': 10,
        'pageNo': 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        
        # 실제 어떤 응답이 오는지 디버깅을 위해 출력
        if response.status_code != 200:
            print(f"Error Code: {response.status_code}")
            print(f"Response Content: {response.text}") # 서버가 보낸 에러 메시지 확인
            return None
            
        return response.json()
    except Exception as e:
        print(f"Connection Error: {e}")
        return None

# 2. store at MinIO
def store(data, filename):
    # MinIO 연결
    s3 = boto3.client('s3', 
        endpoint_url=os.getenv('MINIO_ENDPOINT'),
        aws_access_key_id=os.getenv('MINIO_ACCESS_KEY'),
        aws_secret_access_key=os.getenv('MINIO_SECRET_KEY'))

    # 3. Bronze Bucket에 저장
    bucket = "bronze-zone"
    # 버킷 생성
    try:
        s3.head_bucket(Bucket=bucket)
    except:
        print(f"Creating bucket: {bucket}")
        s3.create_bucket(Bucket=bucket)
    import json
    body = json.dumps(data, ensure_ascii=False)
    
    s3.put_object(Bucket=bucket, Key=filename, Body=body)
    print(f"Successfully stored {filename} in MinIO.")

if __name__ == "__main__":
    for url, filename in urls.items():
        print(f"Fetching: {filename}...")
        raw_api_data = fetch_data(url)

        if raw_api_data is not None:
            try:
                # 1단계: response > body > items 순차 접근
                body = raw_api_data.get('response', {}).get('body', {})
                items_dict = body.get('items')

                # 2단계: items가 None이 아니고, 그 안에 'item'이 있는지 확인
                if items_dict and 'item' in items_dict:
                    items_only = items_dict['item']
                    store(items_only, filename)
                else:
                    print(f"No items found for {filename}, storing raw or skipping.")
                    store(raw_api_data, filename)
            except Exception as e:
                print(f"Parsing error for {filename}: {e}")
                store(raw_api_data, filename)
        else:
            print(f"Failed to fetch data for {filename} (API returned None)")