import os
import json
import boto3
import psycopg2
import re
from datetime import datetime
from dotenv import load_dotenv
import set_client
import logging
import requests
import math

def clean_text(text):
    """[cleansing] HTML 태그 제거 및 불필요한 공백 정리"""
    if not text: return ""
    # HTML 태그 제거
    text = re.sub(r'<[^>]*>', '', text)
    # 특수문자 정리, 연속 공백 제거
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# pagenation
def fetch_all_data(api_url, service_key):
    all_data = []
    page_no = 1
    num_of_rows = 100  # 한 번에 가져올 양 (API 허용치 내 최대값 권장)
    
    while True:
        params = {
            'serviceKey': service_key,
            'pageNo': page_no,
            'numOfRows': num_of_rows,
            'type': 'json'
        }
        
        try:
            response = requests.get(api_url, params=params, timeout=10)
            res_data = response.json()
            
            # 1. 응답 구조 확인 (API마다 다를 수 있음)
            body = res_data.get('body', {})
            items = body.get('items', [])
            total_count = body.get('totalCount', 0)
            
            if not items:
                logging.info("더 이상 가져올 데이터가 없습니다.")
                break
                
            all_data.extend(items)
            
            # 2. 로그 출력 (진행 상황 파악용)
            total_pages = math.ceil(total_count / num_of_rows)
            logging.info(f"Progress: {page_no}/{total_pages} pages (Collected: {len(all_data)}/{total_count})")
            
            # 3. 종료 조건: 현재까지 모은 데이터가 totalCount보다 크거나 같으면 종료
            if len(all_data) >= total_count:
                break
                
            page_no += 1
            
        except Exception as e:
            logging.error(f"Error at page {page_no}: {e}")
            break
            
    return all_data

def process_bronze_to_silver(prefix):
    BUCKET = "bronze"
    try:
        # Bronze에서 정제할 파일 목록 가져오기
        response = set_client.s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix+'/')
        if 'Contents' not in response:
            print("처리할 새로운 데이터가 없습니다.")
            return

        conn = set_client.get_db_conn()
        cur = conn.cursor()

        for obj in response['Contents']:
            file_key = obj['Key']
            print(f"[*] Processing: {file_key}")
            
            # 파일 내용 읽기
            file_obj = set_client.s3.get_object(Bucket=BUCKET, Key=file_key)
            raw_data = json.loads(file_obj['Body'].read().decode('utf-8'))
            items = raw_data.get('items', [])
            print(f"[*] {file_key} 파일에서 {len(items)}개의 아이템을 추출했습니다.")

            # 데이터 정제 및 DB 적재
            if prefix=="drug_info":
                process_drug_info(cur, items)
            else:
                process_taboo_info(cur, items)
        
        conn.commit()
        print("[+] Silver Zone 적재 완료.")
        
    except Exception as e:
        print(f"[!] 에러 발생: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()

# e약은요
def process_drug_info(cur, raw_items):
    upsert_query = """
        INSERT INTO silver_drug_info 
        (drug_id, name, company, efficacy, usage, cautions, interactions, side_effects, update_date, source_api)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (drug_id) DO UPDATE SET
            efficacy = EXCLUDED.efficacy,
            usage = EXCLUDED.usage,
            update_date = EXCLUDED.update_date;
    """
    
    for item in raw_items:
        # 데이터 정제
        drug_id = str(item.get('itemSeq', '')).strip()
        if not drug_id or drug_id == 'None': continue
    
        name = clean_text(item.get('itemName'))
        company = clean_text(item.get('entpName'))
        efficacy = clean_text(item.get('efcyQesitm'))
        usage = clean_text(item.get('useMethodQesitm'))
        
        # None + None 방지
        atpn_warn = item.get('atpnWarnQesitm') or ""
        atpn = item.get('atpnQesitm') or ""
        cautions = clean_text(atpn_warn + " " + atpn)
        
        interactions = clean_text(item.get('intrcQesitm'))
        side_effects = clean_text(item.get('seQesitm'))
        update_date = item.get('updateDe').replace('-', '') if item.get('updateDe') else None
        
        
        cur.execute(upsert_query, (
            drug_id, name, company, efficacy, usage, cautions, interactions, side_effects, update_date, '식품의약품안전처_의약품개요정보(e약은요)'
        ))

# dur: 병용금기정보
def process_taboo_info(cur, raw_items):
    upsert_query = """
        INSERT INTO silver_taboo_info
        (drug_a_id, drug_a_ingr, drug_b_id, drug_b_ingr, prohbt_content, update_date, source_api)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (drug_a_id, drug_b_id) DO UPDATE SET -- 복합키 conflict 처리
            prohbt_content = EXCLUDED.prohbt_content,
            update_date = EXCLUDED.update_date;
    """
    
    for item in raw_items:
        # 데이터 정제
        drug_a_id = str(item.get('ITEM_SEQ', '')).strip()
        drug_b_id = str(item.get('MIXTURE_ITEM_SEQ', '')).strip()
        if not drug_a_id or not drug_b_id: continue
        
        # 성분명 정제 (None 체크 강화)
        main_ingr_raw = item.get('MAIN_INGR')
        if main_ingr_raw:
            # ']' 가 없는 경우를 대비해 예외처리 추가
            drug_a_ingr = main_ingr_raw.split(']')[-1].strip()
        else:
            drug_a_ingr = ""
        
        drug_b_ingr = item.get('MIXTURE_INGR_KOR_NAME')
        prohbt_content = clean_text(item.get('PROHBT_CONTENT'))
        update_date = item.get('CHANGE_DATE').replace('-', '') if item.get('CHANGE_DATE') else None
        
        
        cur.execute(upsert_query, (
            drug_a_id, drug_a_ingr, drug_b_id, drug_b_ingr, prohbt_content, update_date, '식품의약품안전처_의약품안전사용서비스(DUR)품목정보'
        ))

def integrate_to_final():
    conn = set_client.get_db_conn()
    cur = conn.cursor()

    # silver_drug_info를 기반으로 silver_taboo_info에서 금기약물을 리스트화

    query = """
    INSERT INTO silver_drug_integration (
        drug_id, name_ko, entname, indications, dosage, 
        warnings, category, updated_date, combination_contraindication, source_api_list
    )
    SELECT 
        info.drug_id,
        info.name,
        info.company,
        info.efficacy,
        info.usage,
        -- 금기 사유와 일반 주의사항을 합쳐서 저장
        TRIM(COALESCE(string_agg(DISTINCT taboo.prohbt_content, ' | '), '') || ' ' || info.cautions),
        MAX(taboo.source_api), -- 카테고리 대신 출처 정보를 임시 활용하거나 매핑 가능
        MAX(info.update_date),
        -- 병용금기 약물 ID들을 배열로 집계
        array_agg(DISTINCT taboo.drug_b_id) FILTER (WHERE taboo.drug_b_id IS NOT NULL),
        ARRAY['e약은요', 'DUR']
    FROM silver_drug_info info
    LEFT JOIN silver_taboo_info taboo ON info.drug_id = taboo.drug_a_id
    GROUP BY info.drug_id, info.name, info.company, info.efficacy, info.usage, info.cautions
    ON CONFLICT (drug_id) DO UPDATE SET
        indications = EXCLUDED.indications,
        dosage = EXCLUDED.dosage,
        warnings = EXCLUDED.warnings,
        combination_contraindication = EXCLUDED.combination_contraindication,
        updated_date = EXCLUDED.updated_date;
    """

    try:
        print("[*] 데이터 통합 시작")
        cur.execute(query)
        conn.commit()
        print("[+] silver_drug_integration 테이블 통합 완료.")
    except Exception as e:
        print(f"[!] 통합 중 에러 발생: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    process_bronze_to_silver("drug_info")
    process_bronze_to_silver("taboo_info")
    integrate_to_final()