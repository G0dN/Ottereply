import time
import traceback
from typing import Optional

from filelock import FileLock
from loguru import logger

from config import settings
from db import Database
from discuz_client import DiscuzClient, RateLimitError
from models import ReplyJob


class Worker:
    def __init__(self, client: DiscuzClient) -> None:
        self.client: DiscuzClient = client
        self.lock_path: str = settings.BOT_LOCK_FILE
        self.running: bool = True

    def process_job(self, job: ReplyJob) -> Optional[int]:
        logger.info(
            "Processing job id={} type={} tid={} fid={} source_pid={}",
            job.id,
            job.job_type,
            job.tid,
            job.fid,
            job.source_pid,
        )

        with FileLock(self.lock_path, timeout=60):
            self.client.ensure_logged_in()

            try:
                if job.job_type == "quote_reply" and job.source_pid:
                    resp = self.client.reply_thread_with_quote(
                        job.fid, job.tid, job.source_pid, job.reply_message
                    )
                    bot_pid = self._extract_pid_from_redirect(resp, job.tid)
                else:
                    resp = self.client.reply_thread(
                        job.fid, job.tid, job.reply_message
                    )
                    bot_pid = self._extract_pid_from_redirect(resp, job.tid)
            except RuntimeError as e:
                if "formhash" in str(e).lower():
                    logger.warning("formhash not found, session may be expired")
                    self.client.maybe_renew_session()
                    resp = self.client.reply_thread(
                        job.fid, job.tid, job.reply_message
                    )
                    bot_pid = self._extract_pid_from_redirect(resp, job.tid)
                else:
                    raise

            verified = self.client.verify_reply(job.tid, job.reply_message)
            if not verified:
                raise RuntimeError(
                    "Reply verification failed: content not found on thread page"
                )

        logger.info("Job {} completed successfully", job.id)
        return bot_pid

    def _extract_pid_from_redirect(self, html: str, tid: int) -> Optional[int]:
        bot_pids = self.client.find_bot_posts(tid, html=html)
        if bot_pids:
            return bot_pids[-1]
        import re
        match = re.search(r"pid=(\d+)", html)
        return int(match.group(1)) if match else None

    def run_once(self) -> Optional[ReplyJob]:
        with Database() as db:
            job = db.fetch_next_job()
            if not job:
                return None

            db.mark_processing(job.id)

            try:
                bot_pid = self.process_job(job)
                db.mark_sent(job.id, bot_pid)
                return job
            except RateLimitError:
                db.mark_failed(job.id, "Rate limited — will retry after sleep")
                logger.warning("Job {} rate-limited, sleeping 60s before retry", job.id)
                time.sleep(60)
                return None
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                logger.error("Job {} failed: {}", job.id, error_msg)
                db.mark_failed(job.id, error_msg[:65535])
                return None

    def run_forever(self) -> None:
        logger.info("Worker started, polling every {}s", settings.WORKER_SLEEP_SECONDS)
        while self.running:
            try:
                job = self.run_once()
                if not job:
                    time.sleep(settings.WORKER_SLEEP_SECONDS)
            except KeyboardInterrupt:
                logger.info("Worker stopped by user")
                self.running = False
            except Exception as e:
                logger.error("Worker loop error: {}", e)
                time.sleep(settings.WORKER_SLEEP_SECONDS)
