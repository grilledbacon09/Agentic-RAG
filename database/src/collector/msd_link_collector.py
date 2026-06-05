import csv
from datetime import datetime
from urllib.parse import urljoin

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import set_client
from bs4 import BeautifulSoup
from paths import MSD_LINKS_CSV, MSD_SYMPTOMS_HTML, ensure_data_dirs

TARGET_FILE = MSD_SYMPTOMS_HTML
OUTPUT_FILE = MSD_LINKS_CSV

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
        store(extracted_data, f"msd_raw/links_{datetime.now().strftime('%Y%m%d')}.json")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["SYMPTOM_NAME", "URL", "CATEGORY"])
            for item in extracted_data:
                writer.writerow([item["title"], item["url"], item["category"]])
        print(f"[+] links.csv 저장 완료: {output_file} ({len(extracted_data)}건)")

    except Exception as e:
        print(f"오류 발생: {e}")

if __name__ == "__main__":
    ensure_data_dirs()
    load_and_extract(TARGET_FILE)