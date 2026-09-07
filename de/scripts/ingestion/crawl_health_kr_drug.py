"""
[수집 4-2] 약학정보원 - 일반의약품 정보 (Selenium)
로컬 실행 전용
저장경로: s3://bucket/bronze/crawl/health_kr/YYYY-MM-DD/

확인된 일반의약품 체크박스:
  <input type="checkbox" id="tb2_2" onclick="javascript:bohtypeCount('1')">
"""
import re, sys, time
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from loguru import logger
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import requests as rq

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils_s3 import bronze_key, upload_json, key_exists

BASE       = "https://www.health.kr"
SEARCH_URL = f"{BASE}/searchDrug/search_detail.asp"
INITIALS   = list("ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ")


def init_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def extract_drug_links(soup: BeautifulSoup) -> list:
    drugs, seen = [], set()
    for a in soup.find_all("a", href=lambda h: h and "result_drug" in str(h)):
        name = a.get_text(strip=True)
        href = a["href"]
        if name and len(name) > 1 and name not in seen:
            seen.add(name)
            full_url = href if href.startswith("http") else BASE + "/" + href.lstrip("/")
            drugs.append({"name": name, "url": full_url})
    for el in soup.find_all(onclick=lambda x: x and "drug_detailHref" in str(x)):
        onclick = el.get("onclick", "")
        match = re.search(r"drug_detailHref\('([^']+)'\)", onclick)
        if match:
            drug_cd = match.group(1)
            name = el.get_text(strip=True)
            if name and name not in seen:
                seen.add(name)
                drugs.append({"name": name, "url": f"{BASE}/searchDrug/result_drug.asp?drug_cd={drug_cd}"})
    return drugs


def get_total_pages(driver: webdriver.Chrome) -> int:
    try:
        soup = BeautifulSoup(driver.page_source, "lxml")
        paging = soup.find(id="paging")
        if not paging:
            return 1
        tabs = re.findall(r"changeTab\((\d+)\)", str(paging))
        return max(int(t) for t in tabs) if tabs else 1
    except Exception:
        return 1


def go_to_page(driver: webdriver.Chrome, page_num: int) -> bool:
    try:
        links = driver.find_elements(By.CSS_SELECTOR, "#paging span a")
        for link in links:
            onclick = link.get_attribute("onclick") or ""
            if f"changeTab({page_num})" in onclick:
                driver.execute_script("arguments[0].click();", link)
                time.sleep(1.5)
                return True
        driver.execute_script(f"changeTab({page_num});")
        time.sleep(1.5)
        return True
    except Exception as e:
        logger.debug(f"  페이지 {page_num} 이동 실패: {e}")
        return False


def select_otc_only(driver: webdriver.Chrome):
    """일반의약품만 선택: id=tb2_2, onclick=bohtypeCount('1')"""
    try:
        # 모든 보험구분 체크박스 해제 후 일반의약품만 체크
        driver.execute_script("""
            // 모든 보험구분 체크박스 해제
            var allCbs = document.querySelectorAll("input[id^='tb2_']");
            allCbs.forEach(function(cb) { cb.checked = false; });

            // 일반의약품(tb2_2) 체크
            var otcCb = document.getElementById('tb2_2');
            if (otcCb) {
                otcCb.checked = true;
                bohtypeCount('1');
            }
        """)
        time.sleep(0.3)
        logger.debug("  일반의약품 필터 적용 (tb2_2)")
        return True
    except Exception as e:
        logger.warning(f"  일반의약품 필터 실패: {e}")
        return False


def get_all_drugs_for_initial(driver: webdriver.Chrome, initial: str) -> list:
    # 1. 검색 페이지 진입
    driver.get(SEARCH_URL)
    time.sleep(2)

    # 2. 초성 버튼 클릭
    btns = driver.find_elements(By.CSS_SELECTOR, "a[style*='cursor:pointer']")
    for btn in btns:
        if btn.text.strip() == initial:
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.5)
            break
    else:
        logger.warning(f"  [{initial}] 초성 버튼 없음")
        return []

    # 3. 일반의약품 체크박스 선택
    select_otc_only(driver)

    # 4. 검색 버튼 클릭
    search_btn = None
    for selector in ["#btns input", "input[value='검 색']", "input[value='검색']",
                     "#btn_detail_search", "input[type='submit']"]:
        els = driver.find_elements(By.CSS_SELECTOR, selector)
        if els:
            search_btn = els[0]
            break

    if search_btn:
        driver.execute_script("arguments[0].click();", search_btn)
    else:
        driver.execute_script(
            "document.getElementById('frm_search').action='/searchDrug/result_detailmore.asp';"
            "document.getElementById('frm_search').submit();"
        )
    time.sleep(2)

    # 5. 검색결과 더보기 클릭
    for selector in ["#anchor_proy_more", "a[id*='more']", ".showMore a"]:
        els = driver.find_elements(By.CSS_SELECTOR, selector)
        visible = [e for e in els if e.is_displayed()]
        if visible:
            driver.execute_script("arguments[0].click();", visible[0])
            time.sleep(2)
            logger.debug(f"  [{initial}] 더보기 클릭")
            break
    else:
        for xpath in ["//*[contains(text(),'검색결과 더보기')]", "//*[contains(text(),'더보기')]"]:
            els = driver.find_elements(By.XPATH, xpath)
            visible = [e for e in els if e.is_displayed()]
            if visible:
                driver.execute_script("arguments[0].click();", visible[0])
                time.sleep(2)
                break

    # 6. 전체 페이지 확인
    total_pages = get_total_pages(driver)
    logger.debug(f"  [{initial}] 전체 페이지: {total_pages}")

    # 7. 페이지별 수집
    all_drugs, seen_names = [], set()
    for page in range(1, total_pages + 1):
        if page > 1:
            if not go_to_page(driver, page):
                break
        soup = BeautifulSoup(driver.page_source, "lxml")
        page_drugs = extract_drug_links(soup)
        new = [d for d in page_drugs if d["name"] not in seen_names]
        for d in new:
            seen_names.add(d["name"])
        all_drugs.extend(new)
        logger.debug(f"  [{initial}] p{page}/{total_pages}: +{len(new)}개 (누적: {len(all_drugs)}개)")
        if not new:
            break

    return all_drugs


def fetch_drug_detail(drug: dict, session) -> dict:
    res = session.get(drug["url"], timeout=15)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "lxml")

    content = {}
    field_map = {
        "효능효과": ["효능", "효과", "적응"],
        "용법용량": ["용법", "용량", "복용"],
        "주의사항": ["주의"],
        "부작용":   ["부작용", "이상반응"],
        "성분함량": ["성분", "함량"],
        "보관방법": ["보관", "저장"],
    }
    for tag in soup.find_all(["th", "dt", "h3", "h4", "strong"]):
        label = tag.get_text(strip=True)
        for field, keywords in field_map.items():
            if any(kw in label for kw in keywords) and field not in content:
                next_el = tag.find_next(["td", "dd", "p", "div"])
                if next_el:
                    val = next_el.get_text(separator=" ", strip=True)[:1500]
                    if val:
                        content[field] = val

    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "")
        if src and any(kw in src.lower() for kw in ["drug", "pill", "img", "photo", "image"]):
            full_src = src if src.startswith("http") else BASE + src
            images.append({"url": full_src, "alt": alt})

    return {
        "name": drug["name"],
        "url": drug["url"],
        "content": content,
        "images": images,
        "source": "health_kr_drug",
        "crawled_at": datetime.now().isoformat(),
    }


def main():
    logger.info("=" * 50)
    logger.info("약학정보원 일반의약품 수집 시작")
    logger.info("=" * 50)

    detail_session = rq.Session()
    detail_session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Referer": BASE,
    })

    driver = init_driver()
    total = 0

    # 테스트: ㄱ (328개보다 줄어야 정상)
    logger.info("▶ [테스트] 초성 ㄱ (일반의약품만)")
    test_drugs = get_all_drugs_for_initial(driver, "ㄱ")
    logger.info(f"  ㄱ 결과: {len(test_drugs)}개 (328개보다 줄어야 정상)")
    for d in test_drugs[:5]:
        logger.info(f"    - {d['name']}: {d['url'][:60]}")

    if not test_drugs:
        logger.error("결과 없음")
        driver.quit()
        return

    try:
        for initial in INITIALS:
            logger.info(f"\n▶ 초성 [{initial}] 수집 중...")
            drugs = get_all_drugs_for_initial(driver, initial)
            logger.info(f"  [{initial}] 총 {len(drugs)}개")

            for drug in drugs:
                safe = drug["name"][:20].replace(" ", "_").replace("/", "_")
                s3_key = bronze_key("crawl/health_kr", f"drug_{initial}_{safe}.json")
                if key_exists(s3_key):
                    logger.debug(f"  스킵: {drug['name']}")
                    continue
                try:
                    detail = fetch_drug_detail(drug, detail_session)
                    if detail["content"]:
                        upload_json(detail, s3_key)
                        total += 1
                        logger.info(f"  O {drug['name']} 저장 (누적: {total}건)")
                    else:
                        logger.debug(f"  내용 없음: {drug['name']}")
                except Exception as e:
                    logger.error(f"  X {drug['name']}: {str(e)[:80]}")
                time.sleep(0.3)

    finally:
        driver.quit()

    logger.info("=" * 50)
    logger.info(f"완료: {total}건")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()