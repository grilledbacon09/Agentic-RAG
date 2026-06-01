from bs4 import BeautifulSoup
import set_client
from pathlib import Path
import os
import boto3
from dotenv import load_dotenv
from urllib.parse import urljoin
from datetime import datetime

#############################################
# 설정
FILENAME = "symptoms.html"

# 현재 스크립트(msd_collector.py)의 절대 경로를 가져옴
current_file = Path(__file__).resolve()
# src의 부모인 graduation_project(루트)로 이동 후 data/... 경로 생성
# .parent는 한 단계 위 폴더를 의미합니다.
BASE_DIR = current_file.parent.parent
TARGET_FILE = BASE_DIR / "data" / "msd_source" / FILENAME
OUTPUT_FILE = BASE_DIR / "data" / "msd_source" / "links.csv"

base_url = "https://www.msdmanuals.com"
#################################################################

def store(data, filepath="msd_raws/links.json"):
    # MinIO 연결
    bucket = 'bronze'
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

def load_and_extract(filename):
    path = Path(filename)
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            get_links(content)
    except FileNotFoundError:
        print(f"오류: {path} 파일을 찾을 수 없습니다.")

def get_links(html, output_file=OUTPUT_FILE):    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # a 태그 탐색
        a_tags = soup.find_all('a')
        
        if not a_tags:
                print("경고: 추출된 a 태그가 없습니다. HTML 구조를 확인하세요.")
                return
            
        extracted_data = []
        for index, a in enumerate(a_tags):
            # 1. href 속성 존재 여부 체크
            href = a.get('href')
            # 2. 텍스트 존재 여부 체크 (공백 제거)
            text = a.get_text(strip=True)
            
        # local 저장용----------------------------------------------------------------------------------
        #     if href:
        #         category_element = a.find_previous(class_="accordion_accordionHeading__EFFen")
        #         category_text = category_element.get_text(strip=True) if category_element else "미분류"
                
                
        #         url = urljoin(base_url, href)
        #         extracted_data.append([text, url, category_text])
        #     else:
        #         # 데이터 유실 방지를 위해 로그 출력
        #         print(f"로그: {index}번째 태그에 href가 없어 제외됨 (Text: {text})")
                
        # # csv파일에 저장
        # with open(output_file, 'a', encoding='utf-8-sig', newline='') as f:
        #     writer = csv.writer(f)
            
        #     # 헤더
        #     if not os.path.exists(output_file):
        #         writer.writerow(['증상', 'URL', '분류'])
        #     writer.writerows(extracted_data)
            
        #     print(f"성공: {len(a_tags)}개의 링크가 '{output_file}'에 저장되었습니다.")
        # --------------------------------------------------------------------------------------------
            if href and not href.startswith('#') and not href.startswith('javascript'):
                    category_element = a.find_previous(class_="accordion_accordionHeading__EFFen")
                    category_text = category_element.get_text(strip=True) if category_element else "미분류"
                    
                    url = urljoin(base_url, href)
                    # 리스트 대신 딕셔너리 형태로 저장하면 추후 JSON 활용도가 높습니다.
                    extracted_data.append({
                        "title": text,
                        "url": url,
                        "category": category_text
                    })
        store(extracted_data, f"msd_raw/links_{datetime.now().strftime("%Y%m%d")}.json")
                
    except Exception as e:
        print(f"오류 발생: {e}")

if __name__=="__main__":
    load_and_extract(TARGET_FILE)