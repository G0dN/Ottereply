import time
from typing import Optional

from loguru import logger

from config import settings
from db import Database
from discuz_client import DiscuzClient
from agent import generate_reply, generate_followup_reply
from models import ReplyJob


class Scanner:
    def __init__(self, client: DiscuzClient) -> None:
        self.client = client
        self._last_full_scan: float = 0.0

    def scan_new_threads(self) -> None:
        for fid in settings.SCANNER_FORUM_IDS:
            self._scan_forum(fid)

    def _scan_forum(self, fid: int) -> None:
        with Database() as db:
            already_replied = db.get_already_replied_tids(fid)
        logger.info(
            "Scanner starting for fid={}: {} already-replied tids", fid, len(already_replied)
        )

        for page in range(1, settings.SCANNER_PAGE_LIMIT + 1):
            try:
                threads = self.client.get_forum_threads(fid, page)
            except Exception as e:
                logger.warning("Failed to scan forum fid={} page={}: {}", fid, page, e)
                continue

            new_count = 0
            for thread in threads:
                tid = thread["tid"]
                if tid in already_replied:
                    continue

                try:
                    html = self.client.get_thread_page(tid)
                    source_message = self._extract_first_post(html)
                    context = self.client.extract_thread_context(tid)
                except Exception as e:
                    logger.warning("Failed to fetch thread tid={}: {}", tid, e)
                    continue

                reply_message = generate_reply(
                    source_subject=thread["subject"],
                    source_message=source_message,
                    context=context,
                )

                with Database() as db:
                    db.insert_job(
                        tid=tid,
                        fid=fid,
                        job_type="reply",
                        source_pid=None,
                        source_authorid=None,
                        source_subject=thread["subject"],
                        source_message=source_message,
                        reply_message=reply_message,
                    )

                already_replied.add(tid)
                new_count += 1
                logger.info("New thread tid={} subject={}", tid, thread["subject"][:50])

            if new_count == 0 and page == 1:
                break
            time.sleep(2)

    def check_quotes(self) -> None:
        logger.info("check_quotes: starting")
        with Database() as db:
            completed = db.get_completed_jobs(job_type="reply")
        logger.info("check_quotes: {} completed reply jobs", len(completed))

        if not completed:
            logger.info("check_quotes: no completed jobs, skip")
            return

        for job in completed:
            if not job.bot_pid:
                logger.info("check_quotes: tid={} no bot_pid, skip", job.tid)
                continue

            logger.info(
                "check_quotes: checking tid={} bot_pid={}",
                job.tid, job.bot_pid,
            )

            with Database() as db:
                quote_jobs = db.get_completed_jobs(job_type="quote_reply")
            replied_pids = {
                qj.source_pid for qj in quote_jobs if qj.tid == job.tid and qj.source_pid
            }
            logger.info(
                "check_quotes: tid={} replied_pids={}",
                job.tid, replied_pids,
            )

            try:
                all_bot_pids = self.client.find_bot_posts(job.tid)
                if job.bot_pid not in all_bot_pids:
                    all_bot_pids.append(job.bot_pid)
            except Exception:
                all_bot_pids = [job.bot_pid]

            logger.info(
                "check_quotes: tid={} all_bot_pids={}",
                job.tid, all_bot_pids,
            )

            try:
                quotes = self.client.find_quotes_of_bot(
                    job.tid, [job.bot_pid], replied_pids
                )
            except Exception as e:
                logger.warning(
                    "Failed to check quotes for tid={}: {}", job.tid, e
                )
                continue

            logger.info(
                "check_quotes: tid={} found {} new quotes",
                job.tid, len(quotes),
            )

            for quote in quotes:
                with Database() as db:
                    if db.has_quote_reply(job.tid, quote["source_pid"]):
                        logger.info(
                            "check_quotes: tid={} pid={} already replied, skip",
                            job.tid, quote["source_pid"],
                        )
                        continue

                reply_message = generate_followup_reply(
                    source_author=quote["source_author"],
                    source_subject=job.source_subject,
                    context=self.client.extract_thread_context(job.tid),
                )

                with Database() as db:
                    db.insert_job(
                        tid=job.tid,
                        fid=job.fid,
                        job_type="quote_reply",
                        source_pid=quote["source_pid"],
                        source_authorid=None,
                        source_subject=job.source_subject,
                        source_message=None,
                        reply_message=reply_message,
                        parent_job_id=job.id,
                    )

                logger.info(
                    "New quote reply for tid={} source_pid={} by {}",
                    job.tid,
                    quote["source_pid"],
                    quote["source_author"],
                )

            time.sleep(2)

    @staticmethod
    def _extract_first_post(html: str) -> str:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for td in soup.find_all("td", class_="t_f"):
            text = td.get_text("\n", strip=True)
            if text:
                return text[:2000]

        for div in soup.find_all("div", class_="t_f"):
            text = div.get_text("\n", strip=True)
            if text:
                return text[:2000]

        return ""
