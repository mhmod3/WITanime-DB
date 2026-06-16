import cloudscraper
import re
import json
import base64
import time
import os
import signal
import sys
import threading
import shutil
import zipfile
import hashlib
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests.exceptions import RequestException, Timeout, ConnectionError
from urllib.parse import urlparse

# ==================================================================
# 1. الإعدادات العامة والمتغيرات العالمية
# ==================================================================
shutdown_flag = False
task1_running = False
task2_running = False
task_lock = threading.Lock()
file_locks = {}
file_locks_lock = threading.Lock()

# مسارات المجلدات (تم تغيير JSON_DIR إلى data)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")          # المجلد الرئيسي للبيانات
BACKUP_DIR = os.path.join(BASE_DIR, "backup")
STATE_FILE = os.path.join(DATA_DIR, ".state.json")  # ملف تتبع التغييرات

# إنشاء المجلدات إذا لم تكن موجودة
for dir_path in [DATA_DIR, BACKUP_DIR]:
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
        print(f"[Init] Created directory: {dir_path}")

# متغيرات GitHub Actions (تؤخذ من البيئة)
GITHUB_TOKEN = os.environ.get("WITANIME_TOKEN")
GITHUB_REPOSITORY = os.environ.get("WITANIME_REPO")
if GITHUB_TOKEN and GITHUB_REPOSITORY:
    GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases"
else:
    GITHUB_API_URL = None
    print("[WARN] GITHUB_TOKEN or GITHUB_REPOSITORY not set. Release publishing disabled.")

# ==================================================================
# 2. معالج الإشارات
# ==================================================================
def signal_handler(sig, frame):
    global shutdown_flag
    print("\n\n[!] Keyboard interrupt received. Shutting down gracefully...")
    shutdown_flag = True

signal.signal(signal.SIGINT, signal_handler)

# ==================================================================
# 3. التعابير النمطية ودوال فك التشفير (نفس السابق)
# ==================================================================
RE_ANIME_SLUG = re.compile(r'/anime/([^/]+)/?$')
RE_MAL_ID = re.compile(r'/anime/(\d+)')
RE_EPISODE_COUNT = re.compile(r'عدد الحلقات:\s*(\d+)')
RE_EPISODE_COUNT_GENERAL = re.compile(r'عدد\s*الحلقات\s*[:\-]\s*(\d+)')
RE_ZG = re.compile(r'var _zG="([^"]+)"')
RE_ZH = re.compile(r'var _zH="([^"]+)"')
RE_SCRIPT_FINDER = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
RE_PROCESSED_EPISODE = re.compile(
    r'(?:var|let|const|window\.)?\s*processedEpisodeData\s*=\s*["\']([^"\']+)["\'];?',
    re.DOTALL
)

def hex_to_bytes(hex_str: str) -> bytes:
    if len(hex_str) % 2 != 0:
        hex_str = '0' + hex_str
    return bytes(int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2))

def xor_decrypt(hex_data: str, key: str) -> str:
    data_bytes = hex_to_bytes(hex_data)
    return ''.join(chr(data_bytes[i] ^ ord(key[i % len(key)])) for i in range(len(data_bytes)))

def extract_var(var_name: str, js_code: str):
    pattern = rf'var {var_name} = (\[.*?\]|\{{.*?\}});'
    match = re.search(pattern, js_code, re.DOTALL)
    if not match:
        return None
    value_str = match.group(1)
    value_str = value_str.replace("'", '"')
    try:
        return json.loads(value_str)
    except json.JSONDecodeError:
        if value_str.startswith('[') and value_str.endswith(']'):
            items = re.findall(r'"([^"]*)"', value_str)
            return items
        return None

def decode_episode_data(encoded_string):
    parts = encoded_string.split('.')
    if len(parts) != 2:
        raise ValueError("Invalid encoded data format")
    part1 = base64.b64decode(parts[0])
    part2 = base64.b64decode(parts[1])
    result = bytearray()
    for i, b in enumerate(part1):
        result.append(b ^ part2[i % len(part2)])
    return json.loads(result.decode('utf-8'))

def extract_episode_urls(html, base_domain):
    match = RE_PROCESSED_EPISODE.search(html)
    if not match:
        return None
    encoded_data = match.group(1)
    try:
        episodes = decode_episode_data(encoded_data)
    except Exception as e:
        print(f"    Failed to decode processedEpisodeData: {e}")
        return None
    links = []
    for ep in episodes:
        if 'url' in ep:
            raw = ep['url']
            if raw.startswith('/'):
                full = f"{base_domain}{raw}"
            elif not raw.startswith('http'):
                full = f"{base_domain}/{raw}"
            else:
                full = raw
            links.append({
                'url': full,
                'title': ep.get('title', ''),
                'number': ep.get('number', None)
            })
    return links

def decode_type1_zG_zH(html):
    zG_match = RE_ZG.search(html)
    zH_match = RE_ZH.search(html)
    if not zG_match or not zH_match:
        return []
    try:
        resourceRegistry = json.loads(base64.b64decode(zG_match.group(1)).decode('utf-8'))
        configRegistry = json.loads(base64.b64decode(zH_match.group(1)).decode('utf-8'))
    except Exception:
        return []
    results = []
    for i in range(len(resourceRegistry)):
        try:
            resource_data = resourceRegistry[i]
            config_settings = configRegistry[i]
            resource_data = resource_data[::-1]
            resource_data = re.sub(r'[^A-Za-z0-9+/=]', '', resource_data)
            index_key = base64.b64decode(config_settings['k']).decode('utf-8')
            param_offset = config_settings['d'][int(index_key)]
            decoded = base64.b64decode(resource_data).decode('utf-8')
            result = decoded[:-param_offset]
            results.append(result)
        except Exception:
            continue
    return results

def decode_type2_m_p_s(html):
    if 'var _m' not in html or 'var _p0' not in html:
        return []
    all_scripts = RE_SCRIPT_FINDER.findall(html)
    found_script = None
    for script in all_scripts:
        if 'var _m' in script and 'var _p0' in script:
            found_script = script
            break
    if not found_script:
        return []
    js_code = found_script
    _m = extract_var('_m', js_code)
    _p0 = extract_var('_p0', js_code)
    _p1 = extract_var('_p1', js_code)
    _p2 = extract_var('_p2', js_code)
    _p3 = extract_var('_p3', js_code)
    _p4 = extract_var('_p4', js_code)
    _p5 = extract_var('_p5', js_code)
    _p6 = extract_var('_p6', js_code)
    _p7 = extract_var('_p7', js_code)
    _p8 = extract_var('_p8', js_code)
    _s = extract_var('_s', js_code)
    _t = extract_var('_t', js_code)
    _p_list = [_p0, _p1, _p2, _p3, _p4, _p5, _p6, _p7, _p8]
    if not _m or not _t or not _s:
        return []
    secret_b64 = _m.get('r')
    if not secret_b64:
        return []
    try:
        secret = base64.b64decode(secret_b64).decode('utf-8')
    except Exception:
        return []
    count = int(_t.get('l', 0))
    results = []
    for i in range(count):
        chunks = _p_list[i] if i < len(_p_list) and _p_list[i] else []
        seq_raw = _s[i] if i < len(_s) else ''
        if not chunks or not seq_raw:
            continue
        try:
            seq_decrypted = xor_decrypt(seq_raw, secret)
            try:
                seq = json.loads(seq_decrypted)
            except json.JSONDecodeError:
                continue
            decrypted_parts = [xor_decrypt(chunk, secret) for chunk in chunks]
            arranged = [''] * len(seq)
            for j, pos in enumerate(seq):
                if j < len(decrypted_parts):
                    arranged[pos] = decrypted_parts[j]
            final_url = ''.join(arranged)
            results.append(final_url)
        except Exception:
            continue
    return results

def sanitize_filename(name: str) -> str:
    invalid_chars = r'[\\/*?:"<>|]'
    name = re.sub(invalid_chars, '_', name)
    return name.strip('. ')

def get_base_domain(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"

def extract_anime_details(anime_html, anime_url):
    soup = BeautifulSoup(anime_html, 'html.parser')
    anime_name = None
    title_tag = soup.find('h1', class_='anime-details-title')
    if title_tag:
        anime_name = title_tag.get_text(strip=True)
    if not anime_name:
        match = RE_ANIME_SLUG.search(anime_url)
        if match:
            anime_name = match.group(1).replace('-', ' ').title()
    mal_id = None
    mal_link = soup.find('a', class_='anime-mal')
    if mal_link and mal_link.get('href'):
        match = RE_MAL_ID.search(mal_link['href'])
        if match:
            mal_id = match.group(1)
    anime_type = None
    for div in soup.find_all('div', class_='anime-info'):
        span = div.find('span')
        if span and 'النوع:' in span.get_text():
            link = div.find('a')
            if link:
                anime_type = link.get_text(strip=True)
                break
    total_episodes = 0
    for div in soup.find_all('div', class_='anime-info'):
        span = div.find('span')
        if span and 'عدد الحلقات' in span.get_text():
            text = div.get_text()
            match = RE_EPISODE_COUNT.search(text)
            if match:
                total_episodes = int(match.group(1))
                break
    if total_episodes == 0:
        text = soup.get_text()
        match = RE_EPISODE_COUNT_GENERAL.search(text)
        if match:
            total_episodes = int(match.group(1))
    return anime_name, mal_id, total_episodes, anime_type

# ==================================================================
# 4. دوال الشبكة وإعادة المحاولة
# ==================================================================
def create_scraper_with_retries():
    scraper = cloudscraper.create_scraper()
    retry_strategy = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[408, 429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    scraper.mount("http://", adapter)
    scraper.mount("https://", adapter)
    return scraper

def request_with_retry(scraper, url, max_retries=5, timeout=45):
    for attempt in range(1, max_retries + 1):
        try:
            response = scraper.get(url, timeout=timeout)
            if response.status_code == 200:
                return response
            else:
                if attempt == max_retries:
                    print(f"    Failed after {max_retries} attempts: status {response.status_code}")
                else:
                    wait = 2 ** attempt
                    print(f"    Attempt {attempt} failed (status {response.status_code}), retrying in {wait}s...")
                    time.sleep(wait)
        except (RequestException, Timeout, ConnectionError) as e:
            if attempt == max_retries:
                print(f"    Error after {max_retries} attempts: {str(e)}")
            else:
                wait = 2 ** attempt
                print(f"    Attempt {attempt} error: {str(e)}, retrying in {wait}s...")
                time.sleep(wait)
    return None

# ==================================================================
# 5. دوال إدارة الملفات مع الأقفال
# ==================================================================
def get_file_lock(filepath):
    with file_locks_lock:
        if filepath not in file_locks:
            file_locks[filepath] = threading.Lock()
        return file_locks[filepath]

def load_json_file(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        print(f"    [WARN] File {filepath} is corrupted, attempting to restore from backup...")
        backup_path = filepath.replace(DATA_DIR, BACKUP_DIR)
        if os.path.exists(backup_path):
            try:
                with open(backup_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                print(f"    [Recovered] Restored and overwritten {filepath} from backup.")
                return data
            except Exception as e:
                print(f"    [ERROR] Failed to restore from backup: {e}")
        return None

def save_json_file(filepath, data):
    lock = get_file_lock(filepath)
    with lock:
        if os.path.exists(filepath):
            backup_path = filepath.replace(DATA_DIR, BACKUP_DIR)
            try:
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                shutil.copy2(filepath, backup_path)
                print(f"    [Backup] Created backup: {backup_path}")
            except Exception as e:
                print(f"    [Backup] Failed to create backup: {e}")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"    [ERROR] Failed to save {filepath}: {e}")
            return False

def is_data_fresh(filepath, max_age_hours):
    if not os.path.exists(filepath):
        return False
    data = load_json_file(filepath)
    if not data:
        return False
    anime_name = next(iter(data)) if data else None
    if not anime_name:
        return False
    last_updated_str = data.get(anime_name, {}).get("last_updated")
    if not last_updated_str:
        return False
    try:
        last_updated = datetime.fromisoformat(last_updated_str)
        age = (datetime.now() - last_updated).total_seconds() / 3600
        return age < max_age_hours
    except (ValueError, TypeError):
        return False

# ==================================================================
# 6. دوال تتبع الحالة (الهاش)
# ==================================================================
def compute_file_hash(filepath):
    """حساب SHA-256 لمحتوى ملف JSON (بدون ترتيب المفاتيح)"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # نعيد ترتيب المفاتيح لضمان ثبات الهاش
        sorted_data = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(sorted_data.encode('utf-8')).hexdigest()
    except Exception:
        return None

def compute_dir_hashes(data_dir):
    """حساب هاش لكل ملف JSON في المجلد"""
    hashes = {}
    for filename in os.listdir(data_dir):
        if filename.endswith('.json') and filename != '.state.json':
            filepath = os.path.join(data_dir, filename)
            h = compute_file_hash(filepath)
            if h:
                hashes[filename] = h
    return hashes

def load_state():
    """تحميل الحالة السابقة من ملف .state.json"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    """حفظ الحالة الحالية"""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save state: {e}")
        return False

def has_changes(new_hashes, old_state, scope='full'):
    """
    مقارنة الهاشات الجديدة مع القديمة.
    scope='full' تقارن كل الملفات.
    scope='partial' تقارن فقط الملفات المحددة في قائمة (تُمرر كـ keys)
    """
    if scope == 'full':
        old_hashes = old_state.get('full', {})
        return new_hashes != old_hashes
    elif scope == 'partial':
        old_partial = old_state.get('partial', {})
        changed = False
        for key, new_hash in new_hashes.items():
            if old_partial.get(key) != new_hash:
                changed = True
                break
        return changed
    return False

# ==================================================================
# 7. دوال الضغط والنشر في Releases
# ==================================================================
def create_zip(source_dir, output_zip, file_list=None):
    """
    ضغط محتويات source_dir إلى output_zip.
    إذا تم تمرير file_list (قائمة بأسماء الملفات)، يتم ضغطها فقط.
    ضغط متوسط (ZIP_DEFLATED مع compression level 6)
    """
    if not os.path.exists(source_dir):
        return False
    try:
        with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
            if file_list:
                for fname in file_list:
                    filepath = os.path.join(source_dir, fname)
                    if os.path.isfile(filepath):
                        zipf.write(filepath, arcname=fname)
                    else:
                        print(f"    [ZIP] Warning: {fname} not found, skipping.")
            else:
                for root, dirs, files in os.walk(source_dir):
                    for file in files:
                        if file == '.state.json':
                            continue
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, source_dir)
                        zipf.write(full_path, arcname=arcname)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to create zip: {e}")
        return False

def publish_release(zip_path, release_name, tag_name, release_body=""):
    """نشر إصدار على GitHub Releases باستخدام API"""
    if not GITHUB_API_URL:
        print("[ERROR] GitHub API not configured. Cannot publish release.")
        return False
    if not os.path.exists(zip_path):
        print(f"[ERROR] Zip file {zip_path} not found.")
        return False

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # إنشاء الإصدار
    release_data = {
        "tag_name": tag_name,
        "name": release_name,
        "body": release_body,
        "draft": False,
        "prerelease": False
    }
    try:
        resp = requests.post(GITHUB_API_URL, json=release_data, headers=headers)
        if resp.status_code not in (201, 200):
            print(f"[ERROR] Failed to create release: {resp.status_code} {resp.text}")
            return False
        release_info = resp.json()
        upload_url = release_info['upload_url'].replace("{?name,label}", "")
    except Exception as e:
        print(f"[ERROR] Exception creating release: {e}")
        return False

    # رفع الملف المضغوط
    try:
        with open(zip_path, 'rb') as f:
            files = {'file': (os.path.basename(zip_path), f, 'application/zip')}
            upload_resp = requests.post(upload_url, files=files, headers=headers)
            if upload_resp.status_code in (201, 200):
                print(f"[SUCCESS] Released {release_name} with zip file.")
                return True
            else:
                print(f"[ERROR] Failed to upload zip: {upload_resp.status_code} {upload_resp.text}")
                return False
    except Exception as e:
        print(f"[ERROR] Exception uploading zip: {e}")
        return False

# ==================================================================
# 8. دالة معالجة الأنمي الرئيسية (نفس السابق مع تعديل المسار)
# ==================================================================
def process_anime(anime_url, scraper, output_dir, max_age_hours=None, force=False):
    print(f"  Processing: {anime_url}")
    anime_response = request_with_retry(scraper, anime_url, max_retries=3)
    if not anime_response:
        print(f"    Failed to fetch anime page after retries.")
        return None
    anime_html = anime_response.text
    anime_name, mal_id, total_episodes, anime_type = extract_anime_details(anime_html, anime_url)
    if not anime_name:
        print("    Could not extract anime name")
        return None
    safe_name = sanitize_filename(anime_name)
    filepath = os.path.join(output_dir, f"{safe_name}.json")
    if not force and max_age_hours is not None:
        if is_data_fresh(filepath, max_age_hours):
            print(f"    Data is fresh (less than {max_age_hours} hours old), skipping.")
            return None
    base_domain = get_base_domain(anime_url)
    if total_episodes == 0:
        print(f"    Episode count not found in HTML, trying processedEpisodeData...")
        episode_links = extract_episode_urls(anime_html, base_domain)
        if episode_links is not None:
            total_episodes = len(episode_links)
            print(f"    Found {total_episodes} episodes from processedEpisodeData")
        else:
            print(f"    Could not determine episode count for {anime_name}, skipping.")
            return None
    is_movie = (anime_type == "Movie")
    is_special = (anime_type == "Special")
    print(f"  {anime_name} [{anime_type}] - {total_episodes} ep")
    json_data = {
        anime_name: {
            "anime_url": anime_url,
            "type": anime_type or "Unknown",
            "mal_id": mal_id or None
        }
    }
    episode_links = extract_episode_urls(anime_html, base_domain)
    if episode_links is not None:
        print(f"    Extracted {len(episode_links)} episode links from processedEpisodeData")
        for ep in episode_links:
            if is_movie:
                key = "movie"
            elif is_special and total_episodes == 1:
                key = "special"
            else:
                key = str(ep.get('number', episode_links.index(ep) + 1))
            ep_response = request_with_retry(scraper, ep['url'], max_retries=2, timeout=30)
            if not ep_response:
                print(f"    Failed to fetch episode {key}, skipping...")
                continue
            if ep_response.status_code != 200:
                print(f"    Episode {key} returned status {ep_response.status_code}, skipping...")
                ep_response.close()
                continue
            ep_html = ep_response.text
            streaming = decode_type1_zG_zH(ep_html)
            downloading = decode_type2_m_p_s(ep_html)
            if streaming or downloading:
                json_data[anime_name][key] = {
                    "streaming_links": streaming,
                    "downloading_links": downloading
                }
            ep_response.close()
            time.sleep(0.5)
    else:
        print("    No processedEpisodeData found, falling back to manual URL building.")
        slug = RE_ANIME_SLUG.search(anime_url)
        if slug:
            slug = slug.group(1)
        else:
            slug = anime_name.lower().replace(' ', '-')
        if is_movie:
            movie_urls = [
                f"{base_domain}/episode/%d9%81%d9%8a%d9%84%d9%85-{slug}/",
                f"{base_domain}/episode/movie-{slug}/",
                f"{base_domain}/movie/{slug}/"
            ]
            for url in movie_urls:
                ep_response = request_with_retry(scraper, url, max_retries=2, timeout=30)
                if ep_response and ep_response.status_code == 200:
                    ep_html = ep_response.text
                    streaming = decode_type1_zG_zH(ep_html)
                    downloading = decode_type2_m_p_s(ep_html)
                    if streaming or downloading:
                        json_data[anime_name]["movie"] = {
                            "streaming_links": streaming,
                            "downloading_links": downloading
                        }
                    ep_response.close()
                    break
                elif ep_response:
                    ep_response.close()
        elif is_special and total_episodes == 1:
            special_urls = [
                f"{base_domain}/episode/%d8%a7%d9%84%d8%ad%d9%84%d9%82%d8%a9-%d8%a7%d9%84%d8%ae%d8%a7%d8%b5%d8%a9-{slug}/",
                f"{base_domain}/episode/special-{slug}/",
                f"{base_domain}/special/{slug}/"
            ]
            for url in special_urls:
                ep_response = request_with_retry(scraper, url, max_retries=2, timeout=30)
                if ep_response and ep_response.status_code == 200:
                    ep_html = ep_response.text
                    streaming = decode_type1_zG_zH(ep_html)
                    downloading = decode_type2_m_p_s(ep_html)
                    if streaming or downloading:
                        json_data[anime_name]["special"] = {
                            "streaming_links": streaming,
                            "downloading_links": downloading
                        }
                    ep_response.close()
                    break
                elif ep_response:
                    ep_response.close()
        else:
            for ep_num in range(1, total_episodes + 1):
                if shutdown_flag:
                    break
                ep_urls = [
                    f"{base_domain}/episode/{slug}-%d8%a7%d9%84%d8%ad%d9%84%d9%82%d8%a9-{ep_num}/",
                    f"{base_domain}/episode/{slug}-episode-{ep_num}/",
                    f"{base_domain}/episode/{slug}-{ep_num}/"
                ]
                found = False
                for url in ep_urls:
                    ep_response = request_with_retry(scraper, url, max_retries=2, timeout=30)
                    if ep_response and ep_response.status_code == 200:
                        ep_html = ep_response.text
                        streaming = decode_type1_zG_zH(ep_html)
                        downloading = decode_type2_m_p_s(ep_html)
                        if streaming or downloading:
                            json_data[anime_name][str(ep_num)] = {
                                "streaming_links": streaming,
                                "downloading_links": downloading
                            }
                        ep_response.close()
                        found = True
                        break
                    elif ep_response:
                        ep_response.close()
                if not found:
                    print(f"    Failed to fetch episode {ep_num} after trying multiple patterns.")
                time.sleep(0.5)
    has_content = False
    for key in json_data[anime_name]:
        if key in ["anime_url", "type", "mal_id"]:
            continue
        if isinstance(json_data[anime_name][key], dict):
            if json_data[anime_name][key].get("streaming_links") or json_data[anime_name][key].get("downloading_links"):
                has_content = True
                break
    if not has_content:
        print(f"    No valid links found for {anime_name}")
        return None
    json_data[anime_name]["last_updated"] = datetime.now().isoformat()
    existing_data = load_json_file(filepath)
    if existing_data:
        if anime_name in existing_data:
            for key, value in json_data[anime_name].items():
                if key not in ["anime_url", "type", "mal_id", "last_updated"]:
                    existing_data[anime_name][key] = value
            existing_data[anime_name]["anime_url"] = json_data[anime_name]["anime_url"]
            existing_data[anime_name]["type"] = json_data[anime_name]["type"]
            existing_data[anime_name]["mal_id"] = json_data[anime_name]["mal_id"]
            existing_data[anime_name]["last_updated"] = json_data[anime_name]["last_updated"]
        else:
            existing_data.update(json_data)
    else:
        existing_data = json_data
    if save_json_file(filepath, existing_data):
        print(f"  Saved {safe_name}.json")
        return existing_data
    else:
        print(f"  Failed to save {safe_name}.json")
        return None

# ==================================================================
# 9. دالة استئناف العمل
# ==================================================================
def resume_from_backup(output_dir=DATA_DIR, backup_dir=BACKUP_DIR):
    if not os.path.exists(backup_dir):
        return
    backup_files = [f for f in os.listdir(backup_dir) if f.endswith('.json')]
    if not backup_files:
        return
    print(f"[Resume] Found {len(backup_files)} backup files. Checking for corrupted files...")
    restored = 0
    for bf in backup_files:
        target_path = os.path.join(output_dir, bf)
        backup_path = os.path.join(backup_dir, bf)
        lock = get_file_lock(target_path)
        with lock:
            if not os.path.exists(target_path):
                try:
                    shutil.copy2(backup_path, target_path)
                    print(f"[Resume] Restored {bf} from backup (missing file).")
                    restored += 1
                except Exception as e:
                    print(f"[Resume] Failed to restore {bf}: {e}")
            else:
                try:
                    with open(target_path, 'r', encoding='utf-8') as f:
                        json.load(f)
                except:
                    try:
                        shutil.copy2(backup_path, target_path)
                        print(f"[Resume] Restored {bf} from backup (corrupted file).")
                        restored += 1
                    except Exception as e:
                        print(f"[Resume] Failed to restore {bf}: {e}")
    if restored > 0:
        print(f"[Resume] Restored {restored} files from backup.")

# ==================================================================
# 10. المهمة الأولى (كل 24 ساعة) – مع النشر الكامل
# ==================================================================
def task1_full_scan():
    global task1_running
    with task_lock:
        if task1_running:
            print("[Task 1] Already running, skipping this execution.")
            return
        task1_running = True
    try:
        print("\n" + "="*60)
        print(f"[Task 1] Starting full scan of all anime pages - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
        resume_from_backup(DATA_DIR, BACKUP_DIR)
        scraper = create_scraper_with_retries()
        scraper.headers.update({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        })
        all_anime_urls = []
        for page in range(1, 74):
            if shutdown_flag:
                break
            list_url = f"https://witanime.you/%d9%82%d8%a7%d8%a6%d9%85%d8%a9-%d8%a7%d9%84%d8%a7%d9%86%d9%85%d9%8a/page/{page}/"
            print(f"\n[Task 1] Fetching page {page}: {list_url}")
            response = request_with_retry(scraper, list_url, max_retries=3)
            if not response:
                print(f"[Task 1] Failed to fetch page {page}, skipping to next page.")
                continue
            soup = BeautifulSoup(response.text, 'html.parser')
            cards = soup.find_all('div', class_='anime-card-container')
            if not cards:
                print(f"[Task 1] No anime cards found on page {page}, stopping pagination.")
                break
            page_urls = []
            for card in cards:
                poster = card.find('div', class_='anime-card-poster')
                if poster:
                    link_tag = poster.find('a', class_='overlay')
                    if link_tag and link_tag.get('href'):
                        href = link_tag['href']
                        if '/anime/' in href:
                            page_urls.append(href)
            if not page_urls:
                print(f"[Task 1] No anime links extracted from page {page}, stopping pagination.")
                break
            all_anime_urls.extend(page_urls)
            print(f"[Task 1] Page {page}: Found {len(page_urls)} links (total so far: {len(all_anime_urls)})")
            response.close()
            time.sleep(0.5)
        print(f"\n[Task 1] Total anime URLs found: {len(all_anime_urls)}")
        processed_count = 0
        for idx, anime_url in enumerate(all_anime_urls, 1):
            if shutdown_flag:
                break
            print(f"\n[Task 1] [{idx}/{len(all_anime_urls)}] Processing: {anime_url}")
            try:
                result = process_anime(anime_url, scraper, DATA_DIR, max_age_hours=20)
                if result:
                    processed_count += 1
            except Exception as e:
                print(f"[Task 1] Error processing {anime_url}: {e}")
            time.sleep(0.5)
        print(f"\n[Task 1] Completed! Processed {processed_count} anime.")
        print("="*60)
        # --- بعد الانتهاء، التحقق من التغييرات والنشر ---
        print("[Task 1] Checking for changes to publish full database...")
        new_hashes = compute_dir_hashes(DATA_DIR)
        old_state = load_state()
        if has_changes(new_hashes, old_state, 'full'):
            print("[Task 1] Changes detected. Creating full database zip...")
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            zip_name = f"full_database_{timestamp}.zip"
            zip_path = os.path.join(BASE_DIR, zip_name)
            if create_zip(DATA_DIR, zip_path, file_list=None):
                new_state = old_state.copy()
                new_state['full'] = new_hashes
                save_state(new_state)
                tag = f"full-db-{timestamp}"
                release_name = f"Full Database {timestamp}"
                publish_release(zip_path, release_name, tag, f"Full database snapshot from {timestamp}")
                try:
                    os.remove(zip_path)
                except:
                    pass
            else:
                print("[Task 1] Failed to create zip.")
        else:
            print("[Task 1] No changes detected. Skipping release.")
    except Exception as e:
        print(f"[Task 1] Error: {str(e)}")
    finally:
        with task_lock:
            task1_running = False

# ==================================================================
# 11. المهمة الثانية (كل ساعة) – النشر الجزئي (المكتمل)
# ==================================================================
def task2_completed():
    global task2_running
    with task_lock:
        if task2_running:
            print("[Task 2] Already running, skipping this execution.")
            return
        task2_running = True
    try:
        print("\n" + "-"*60)
        print(f"[Task 2] Starting scan of completed anime - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("-"*60)
        resume_from_backup(DATA_DIR, BACKUP_DIR)
        scraper = create_scraper_with_retries()
        scraper.headers.update({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        })
        list_url = "https://witanime.you/anime-status/%d9%85%d9%83%d8%aa%d9%85%d9%84/"
        print(f"[Task 2] Fetching: {list_url}")
        response = request_with_retry(scraper, list_url, max_retries=3)
        if not response:
            print("[Task 2] Failed to fetch page.")
            return
        soup = BeautifulSoup(response.text, 'html.parser')
        cards = soup.find_all('div', class_='anime-card-container')
        if not cards:
            print("[Task 2] No anime cards found on page. Page is empty. Skipping task.")
            response.close()
            return
        anime_urls = []
        for card in cards:
            poster = card.find('div', class_='anime-card-poster')
            if poster:
                link_tag = poster.find('a', class_='overlay')
                if link_tag and link_tag.get('href'):
                    href = link_tag['href']
                    if '/anime/' in href:
                        anime_urls.append(href)
        print(f"[Task 2] Found {len(anime_urls)} completed anime.")
        response.close()
        # معالجة كل أنمي
        processed_count = 0
        for idx, anime_url in enumerate(anime_urls, 1):
            if shutdown_flag:
                break
            print(f"\n[Task 2] [{idx}/{len(anime_urls)}] Processing: {anime_url}")
            try:
                result = process_anime(anime_url, scraper, DATA_DIR, max_age_hours=0.5)
                if result:
                    processed_count += 1
            except Exception as e:
                print(f"[Task 2] Error processing {anime_url}: {e}")
            time.sleep(0.5)
        print(f"\n[Task 2] Completed! Processed {processed_count} anime.")
        print("-"*60)
        # --- التحقق من التغييرات في الأنميات المكتملة فقط ---
        print("[Task 2] Checking for changes in completed anime to publish partial database...")
        # استخراج أسماء ملفات الأنميات المكتملة (نفترض أن اسم الملف يساوي الاسم من الرابط)
        completed_names = []
        for url in anime_urls:
            match = RE_ANIME_SLUG.search(url)
            if match:
                slug = match.group(1)
                name = slug.replace('-', ' ').title()
                safe_name = sanitize_filename(name)
                completed_names.append(f"{safe_name}.json")
        # حساب الهاشات لهذه الملفات فقط
        new_hashes = {}
        for fname in completed_names:
            filepath = os.path.join(DATA_DIR, fname)
            if os.path.exists(filepath):
                h = compute_file_hash(filepath)
                if h:
                    new_hashes[fname] = h
        old_state = load_state()
        old_partial = old_state.get('partial', {})
        changed = False
        for fname, new_h in new_hashes.items():
            if old_partial.get(fname) != new_h:
                changed = True
                break
        if changed:
            print("[Task 2] Changes detected. Creating partial database zip...")
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            zip_name = f"partial_database_{timestamp}.zip"
            zip_path = os.path.join(BASE_DIR, zip_name)
            if create_zip(DATA_DIR, zip_path, file_list=completed_names):
                new_state = old_state.copy()
                new_state['partial'] = new_hashes
                save_state(new_state)
                tag = f"partial-db-{timestamp}"
                release_name = f"Partial Database (Completed) {timestamp}"
                publish_release(zip_path, release_name, tag, f"Partial database for completed anime from {timestamp}")
                try:
                    os.remove(zip_path)
                except:
                    pass
            else:
                print("[Task 2] Failed to create zip.")
        else:
            print("[Task 2] No changes detected in completed anime. Skipping release.")
    except Exception as e:
        print(f"[Task 2] Error: {str(e)}")
    finally:
        with task_lock:
            task2_running = False

# ==================================================================
# 12. الوظيفة الرئيسية
# ==================================================================
def main():
    print("="*60)
    print("Witanime Scheduler Service (with GitHub Releases)")
    print("="*60)
    print(f"Data Directory: {DATA_DIR}")
    print(f"Backup Directory: {BACKUP_DIR}")
    print("Task 1: Full scan - publishes full database if changes.")
    print("Task 2: Completed anime scan - publishes partial database if changes.")
    print("Press Ctrl+C to stop.")
    print("="*60)
    # تنفيذ المهمتين فور البدء
    task1_full_scan()
    task2_completed()
    # جدولة المهام (تعليقها لأن GitHub Actions ستتولى الجدولة)
    # في حالة التشغيل المحلي، يمكن تفعيل الجدولة:
    # import schedule
    # schedule.every(24).hours.do(task1_full_scan)
    # schedule.every(1).hours.do(task2_completed)
    # while not shutdown_flag:
    #     schedule.run_pending()
    #     time.sleep(60)

if __name__ == "__main__":
    main()
