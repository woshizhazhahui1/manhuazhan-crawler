import os
import time
import threading
from queue import Queue

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import requests
from tqdm import tqdm

# 全局设置
MAX_WORKERS = 5  # 下载线程数
MAX_RETRIES = 3
DOWNLOAD_ROOT = './manhuazhan_download'
HEADLESS = True  # 是否无头浏览器

class ComicDownloader:
    def __init__(self, comic_url):
        self.comic_url = comic_url
        self.driver = self._init_selenium()
        self.session = requests.Session()
        self.chapter_list = []
        self.download_queue = Queue()

    def _init_selenium(self):
        options = Options()
        if HEADLESS:
            options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1200,800")
        driver = webdriver.Chrome(options=options)
        return driver

    def scroll_to_bottom(self):
        """模拟滚动到底部，触发懒加载"""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        while True:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # 等待加载
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    def get_chapter_list(self):
        print(f"🌐 打开漫画主页：{self.comic_url}")
        self.driver.get(self.comic_url)
        self.scroll_to_bottom()

        # 获取章节元素列表
        elems = self.driver.find_elements(By.CSS_SELECTOR, "div.d-player-list a")
        self.chapter_list = []
        for a in elems:
            title = a.text.strip()
            href = a.get_attribute("href")
            if href and title:
                self.chapter_list.append((title, href))
        print(f"📚 共找到章节数：{len(self.chapter_list)}")

    def get_image_urls(self, chapter_url):
        print(f"🌐 打开章节页面：{chapter_url}")
        self.driver.get(chapter_url)
        self.scroll_to_bottom()
        time.sleep(1)

        # 查找图片标签
        imgs = self.driver.find_elements(By.CSS_SELECTOR, "#chapterContent img")
        if not imgs:
            # 备用选择器，有的网站图片在div#ChapterContent中但img不直接在里面
            imgs = self.driver.find_elements(By.CSS_SELECTOR, "#ChapterContent img")
        img_urls = []
        for img in imgs:
            src = img.get_attribute("src")
            if src and src.startswith("http"):
                img_urls.append(src)
        print(f"📷 找到图片数量：{len(img_urls)}")
        return img_urls

    def download_image(self, img_url, save_path, referer):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": referer,
        }
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.get(img_url, headers=headers, timeout=15)
                resp.raise_for_status()
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                return True
            except Exception as e:
                print(f"❌ 下载失败 {img_url} 重试{attempt}/{MAX_RETRIES}: {e}")
                time.sleep(2)
        return False

    def worker(self):
        while True:
            task = self.download_queue.get()
            if task is None:
                break
            img_url, save_path, referer = task
            if os.path.exists(save_path):
                print(f"📂 已存在，跳过: {save_path}")
                self.download_queue.task_done()
                continue
            success = self.download_image(img_url, save_path, referer)
            if not success:
                print(f"❌ 下载失败，跳过: {img_url}")
            self.download_queue.task_done()

    def run(self):
        self.get_chapter_list()
        if not self.chapter_list:
            print("❌ 未找到任何章节，退出")
            self.driver.quit()
            return

        # 启动下载线程池
        threads = []
        for _ in range(MAX_WORKERS):
            t = threading.Thread(target=self.worker)
            t.daemon = True
            t.start()
            threads.append(t)

        for chapter_title, chapter_url in self.chapter_list:
            safe_title = "".join(c if c.isalnum() or c in "_- " else "_" for c in chapter_title)
            chapter_dir = os.path.join(DOWNLOAD_ROOT, safe_title)
            os.makedirs(chapter_dir, exist_ok=True)

            img_urls = self.get_image_urls(chapter_url)
            if not img_urls:
                print(f"❌ 没有找到图片链接：{chapter_title}")
                continue

            print(f"📥 下载章节：{chapter_title}，共 {len(img_urls)} 张图片")

            for idx, img_url in enumerate(img_urls, 1):
                ext = os.path.splitext(img_url)[1].split("?")[0]
                ext = ext if ext else ".jpg"
                filename = f"{idx:03d}{ext}"
                save_path = os.path.join(chapter_dir, filename)
                self.download_queue.put((img_url, save_path, chapter_url))

        self.download_queue.join()

        for _ in range(MAX_WORKERS):
            self.download_queue.put(None)
        for t in threads:
            t.join()

        self.driver.quit()
        print("✅ 全部章节下载完成！")


if __name__ == "__main__":
    comic_url = "https://www.manhuazhan.com/comic/555980"
    downloader = ComicDownloader(comic_url)
    downloader.run()
