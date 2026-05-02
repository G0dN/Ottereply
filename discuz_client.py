import json
import re
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from loguru import logger

from config import settings


class RateLimitError(RuntimeError):
    pass


class DiscuzClient:
    def __init__(
        self,
        base_url: str = "",
        username: str = "",
        password: str = "",
        cookie_file: str = "",
    ) -> None:
        self.base_url: str = base_url or settings.DISCUZ_BASE_URL
        self.username: str = username or settings.DISCUZ_USERNAME
        self.password: str = password or settings.DISCUZ_PASSWORD
        self.cookie_file: str = cookie_file or settings.BOT_COOKIE_FILE
        self.user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self.session: requests.Session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def load_cookies(self) -> None:
        cookie_path = Path(self.cookie_file)
        if not cookie_path.exists():
            return
        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookie_list = json.load(f)
            # cookie_list may be a list of dicts (browser format) or a dict (bot format)
            if isinstance(cookie_list, list):
                for c in cookie_list:
                    self.session.cookies.set(
                        c.get("name", ""), c.get("value", ""),
                        domain=c.get("domain", ""), path=c.get("path", "/"),
                    )
            else:
                for name, value in cookie_list.items():
                    self.session.cookies.set(name, value)
            logger.info("Cookies loaded from {} ({} entries)", cookie_path, len(cookie_list))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to load cookies: {}", e)

    def save_cookies(self) -> None:
        cookie_path = Path(self.cookie_file)
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cookie_path, "w", encoding="utf-8") as f:
            json.dump(
                requests.utils.dict_from_cookiejar(self.session.cookies),
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info("Cookies saved to {}", cookie_path)

    def is_logged_in(self) -> bool:
        try:
            url = f"{self.base_url}/forum.php"
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
            html = r.text

            _save_debug_html("forum_page", 0, html)

            discuz_uid_match = re.search(r"discuz_uid\s*=\s*'(\d+)'", html)
            discuz_uid = discuz_uid_match.group(1) if discuz_uid_match else "0"
            username_found = self.username in html
            logout_found = "mod=logging&action=logout" in html

            logger.info(
                "Login check: discuz_uid={} username_found={} logout_found={}",
                discuz_uid, username_found, logout_found,
            )

            return discuz_uid != "0"
        except Exception as e:
            logger.warning("Login check HTTP/parse failed: {}", e)
        return False

    def _get_formhash_from_page(self, url: str) -> str:
        r = self.session.get(url, timeout=15)
        r.raise_for_status()
        return self.extract_formhash(r.text)

    def login(self) -> None:
        login_page_url = f"{self.base_url}/member.php?mod=logging&action=login"
        try:
            formhash = self._get_formhash_from_page(login_page_url)
            logger.info("Login page formhash: {}", formhash)
        except RuntimeError:
            logger.warning("No formhash on login page, continuing without it")
            formhash = ""

        payload: dict[str, str] = {
            "username": self.username,
            "password": self.password,
            "loginsubmit": "yes",
            "formhash": formhash,
            "cookietime": "2592000",
        }

        headers = {"Referer": login_page_url}
        response = self.session.post(
            login_page_url, data=payload, headers=headers, timeout=30
        )
        response.raise_for_status()

        self.save_cookies()

        _save_debug_html("login_response", 0, response.text)
        logger.info("Login response saved to logs/debug/login_response_tid0.html")

        logged_in = self.is_logged_in()
        logger.info("Post-login check: logged_in={}", logged_in)

        if not logged_in:
            raise RuntimeError("Login failed — not logged in after POST")

        logger.info("Login successful for user {}", self.username)

    def ensure_logged_in(self) -> None:
        if not self.is_logged_in():
            raise RuntimeError(
                "Not logged in! Please manually log in via browser, "
                "run 'python tools/inject_cookies.py' to update cookies, "
                "then restart the bot."
            )

    def get_thread_page(self, tid: int, page: int = 1) -> str:
        url = f"{self.base_url}/forum.php?mod=viewthread&tid={tid}&page={page}"
        r = self.session.get(url, timeout=15)
        r.raise_for_status()
        return r.text

    @staticmethod
    def extract_formhash(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")

        item = soup.find("input", {"name": "formhash"})
        if item and item.get("value"):
            return str(item["value"])

        match = re.search(r"formhash=([a-zA-Z0-9]+)", html)
        if match:
            return match.group(1)

        raise RuntimeError("formhash not found in page")

    def reply_thread(self, fid: int, tid: int, message: str) -> str:
        reply_page_url = (
            f"{self.base_url}/forum.php"
            f"?mod=post&action=reply&fid={fid}&tid={tid}"
        )
        html = self.session.get(reply_page_url, timeout=15).text
        formhash = self.extract_formhash(html)

        url = f"{reply_page_url}&replysubmit=yes"

        payload = {
            "formhash": formhash,
            "message": message,
            "subject": "",
            "usesig": "1",
            "replysubmit": "true",
        }

        headers = {
            "Referer": reply_page_url,
        }

        r = self.session.post(url, data=payload, headers=headers, timeout=30)
        r.raise_for_status()
        logger.info("Reply POST returned status {}", r.status_code)
        text = r.text

        if "发布成功" in text or "回复发布成功" in text or "post_newreply_succeed" in text:
            logger.info("Reply success indicator found in response")
        elif "需要审核" in text or "moderate" in text.lower() or "审核中" in text:
            logger.warning("Reply may be awaiting moderation — check response")
        elif "验证码" in text or "seccode" in text.lower() or "captcha" in text.lower():
            logger.error("CAPTCHA detected — reply likely blocked")
        elif "您所在的用户组" in text or "无权" in text or "没有权限" in text:
            logger.error("Permission denied — reply blocked by user group")
            _save_debug_html("reply_failure", tid, text)
        elif "两次发表间隔" in text or "灌水" in text:
            logger.warning("Rate limit detected — sleeping 60s")
            raise RateLimitError("Rate limit — need longer interval")
        else:
            _save_debug_html("reply_unknown", tid, text)

        return text

    def reply_thread_with_quote(
        self, fid: int, tid: int, quote_pid: int, message: str
    ) -> str:
        reply_page_url = (
            f"{self.base_url}/forum.php"
            f"?mod=post&action=reply&fid={fid}&tid={tid}&repquote={quote_pid}"
        )
        html = self.session.get(reply_page_url, timeout=15).text
        formhash = self.extract_formhash(html)

        url = (
            f"{self.base_url}/forum.php"
            f"?mod=post&action=reply&fid={fid}&tid={tid}"
            f"&repquote={quote_pid}&replysubmit=yes&inajax=1"
        )

        payload = {
            "formhash": formhash,
            "message": message,
            "usesig": "1",
            "replysubmit": "true",
        }

        headers = {
            "Referer": reply_page_url,
        }

        r = self.session.post(url, data=payload, headers=headers, timeout=30)
        r.raise_for_status()
        logger.info("Quote reply POST returned status {}", r.status_code)
        text = r.text
        if "发布成功" in text or "回复发布成功" in text or "post_newreply_succeed" in text:
            logger.info("Quote reply success indicator found in response")
        elif "需要审核" in text or "moderate" in text.lower():
            logger.warning("Quote reply may be awaiting moderation")
        return text

    def verify_reply(self, tid: int, message: str) -> bool:
        import unicodedata

        raw = message.strip()
        base = raw[5:35] if len(raw) > 35 else raw[:30]
        snippet = unicodedata.normalize("NFKC", base)
        logger.info("Verification snippet: {!r}", snippet)

        html = self.get_thread_page(tid)
        if _normalized_text_contains(html, snippet):
            return True

        last_page = self._get_thread_last_page(tid)
        logger.info("Thread tid={} last_page detected: {}", tid, last_page)
        if last_page > 1:
            html = self.get_thread_page(tid, page=last_page)
            if _normalized_text_contains(html, snippet):
                return True

        logger.warning(
            "Verification failed for tid={}: snippet {!r} not found on page 1 or {}",
            tid, snippet, last_page,
        )
        return False

    def _get_thread_last_page(self, tid: int) -> int:
        html = self.get_thread_page(tid)
        max_page = 1
        for match in re.finditer(rf"tid={tid}(?:&amp;|&).*?page=(\d+)", html):
            max_page = max(max_page, int(match.group(1)))
        if max_page == 1:
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=re.compile(rf"tid={tid}.*page=\d+")):
                href = link.get("href", "")
                match = re.search(r"page=(\d+)", href)
                if match:
                    max_page = max(max_page, int(match.group(1)))
        return max_page

    def maybe_renew_session(self) -> None:
        logger.warning("Session may be expired, clearing cookies and re-logging in")
        cookie_path = Path(self.cookie_file)
        if cookie_path.exists():
            cookie_path.unlink()
        self.session.cookies.clear()
        self.ensure_logged_in()

    # ── forum scanner methods ──────────────────────────────────────────

    def get_forum_threads(self, fid: int, page: int = 1) -> list[dict]:
        url = f"{self.base_url}/forum.php?mod=forumdisplay&fid={fid}&page={page}"
        r = self.session.get(url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        threads: list[dict] = []

        # Only look inside the thread list container
        container = soup.find("div", id="threadlist")
        if not container:
            container = soup.find("div", class_="threadlist")
        if not container:
            container = soup.find("form", id="moderate")

        search_root = container if container else soup

        for link in search_root.find_all(
            "a", href=re.compile(r"mod=viewthread&tid=\d+")
        ):
            href = link.get("href", "")
            tid_match = re.search(r"tid=(\d+)", href)
            if not tid_match:
                continue
            tid = int(tid_match.group(1))
            subject = link.get_text(strip=True)
            if not subject or tid in {t["tid"] for t in threads}:
                continue
            threads.append({"tid": tid, "subject": subject, "href": href})

        logger.info(
            "Scanned forum fid={} page={}: {} threads (container={})",
            fid, page, len(threads),
            "found" if container else "fallback",
        )
        return threads

    def find_bot_posts(self, tid: int, html: str = "") -> list[int]:
        auto_fetch = not bool(html)
        if auto_fetch:
            html = self.get_thread_page(tid)
        bot_pids = self._find_bot_pids_in_html(html)

        if auto_fetch:
            last_page = self._get_thread_last_page(tid)
            if last_page > 1:
                html2 = self.get_thread_page(tid, page=last_page)
                for pid in self._find_bot_pids_in_html(html2):
                    if pid not in bot_pids:
                        bot_pids.append(pid)

        return bot_pids

    def _find_bot_pids_in_html(self, html: str) -> list[int]:
        soup = BeautifulSoup(html, "html.parser")
        bot_pids: list[int] = []

        for div in soup.find_all("div", id=re.compile(r"post_\d+")):
            author = div.find("a", class_="xw1")
            if author and self.username in author.get_text():
                pid_match = re.search(r"post_(\d+)", div.get("id", ""))
                if pid_match:
                    bot_pids.append(int(pid_match.group(1)))

        if not bot_pids:
            for div in soup.find_all("table", id=re.compile(r"pid\d+")):
                author = div.find("a", class_="xw1")
                if author and self.username in author.get_text():
                    pid_match = re.search(r"pid(\d+)", div.get("id", ""))
                    if pid_match:
                        bot_pids.append(int(pid_match.group(1)))

        return bot_pids

    def find_quotes_of_bot(
        self, tid: int, bot_pids: list[int], replied_pids: set[int]
    ) -> list[dict]:
        html = self.get_thread_page(tid)
        quotes = self._parse_quotes_from_html(html, bot_pids, replied_pids)
        if not quotes:
            last_page = self._get_thread_last_page(tid)
            if last_page > 1:
                html = self.get_thread_page(tid, page=last_page)
                quotes = self._parse_quotes_from_html(html, bot_pids, replied_pids)
        return quotes

    def _parse_quotes_from_html(
        self, html: str, bot_pids: list[int], replied_pids: set[int]
    ) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        quotes: list[dict] = []

        for div in soup.find_all("div", id=re.compile(r"post_\d+")):
            current_pid_match = re.search(r"post_(\d+)", div.get("id", ""))
            if not current_pid_match:
                continue
            current_pid = int(current_pid_match.group(1))
            if current_pid in bot_pids or current_pid in replied_pids:
                continue

            author = div.find("a", class_="xw1")
            author_name = author.get_text(strip=True) if author else ""
            if author_name == self.username:
                continue

            for qlink in div.find_all(
                "a", href=re.compile(r"goto=findpost.*pid=\d+")
            ):
                href = qlink.get("href", "")
                pid_match = re.search(r"pid=(\d+)", href)
                if pid_match and int(pid_match.group(1)) in bot_pids:
                    logger.info(
                        "Found quote: post_pid={} author={} quoted_bot_pid={}",
                        current_pid, author_name, int(pid_match.group(1)),
                    )
                    quotes.append({
                        "source_pid": current_pid,
                        "source_author": author_name,
                        "quoted_bot_pid": int(pid_match.group(1)),
                    })
                    break

        if not quotes:
            logger.info(
                "No quotes found: bot_pids={} replied_pids={} scanned {} posts",
                bot_pids, replied_pids,
                len(list(soup.find_all("div", id=re.compile(r"post_\d+")))),
            )

        return quotes

    def extract_thread_context(self, tid: int, max_posts: int = 20) -> str:
        html = self.get_thread_page(tid)
        soup = BeautifulSoup(html, "html.parser")
        lines: list[str] = []

        for div in soup.find_all("div", id=re.compile(r"post_\d+")):
            author_elem = div.find("a", class_="xw1")
            author = author_elem.get_text(strip=True) if author_elem else "?"

            content_parts: list[str] = []
            for td in div.find_all("td", class_="t_f"):
                content_parts.append(td.get_text("\n", strip=True))
            for d in div.find_all("div", class_="t_f"):
                content_parts.append(d.get_text("\n", strip=True))
            content = " ".join(content_parts)
            if not content:
                continue

            text = f"[{author}]: {content}"
            text = text.replace("\n", " ").replace("\r", " ")
            text = " ".join(text.split())[:500]
            lines.append(text)

            if len(lines) >= max_posts:
                break

        return "\n".join(lines)


def _normalized_text_contains(html: str, snippet: str) -> bool:
    import unicodedata
    soup = BeautifulSoup(html, "html.parser")
    texts: list[str] = []

    for td in soup.find_all("td", class_="t_f"):
        texts.append(td.get_text(" ", strip=True))

    if not texts:
        texts.append(soup.get_text(" ", strip=True))

    for text in texts:
        clean = unicodedata.normalize("NFKC", text)
        clean = clean.replace("\n", "").replace("\r", "").replace(" ", "")
        needle = snippet.replace("\n", "").replace("\r", "").replace(" ", "")
        if needle in clean:
            return True

    return False


def _save_debug_html(tag: str, tid: int, html: str) -> None:
    from pathlib import Path

    debug_dir = Path("logs/debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"{tag}_tid{tid}.html"
    path.write_text(html, encoding="utf-8")
    logger.info("Saved debug HTML to {}", path)
