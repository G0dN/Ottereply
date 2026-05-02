import sys
import time

from loguru import logger

from config import settings
from discuz_client import DiscuzClient
from worker import Worker
from scanner import Scanner


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add("logs/worker.log", rotation="50 MB", retention="14 days", level="DEBUG")

    logger.info("Starting Discuz Auto Reply Agent")
    logger.info("Base URL: {}", settings.DISCUZ_BASE_URL)
    logger.info("Running as User: {}", settings.DISCUZ_USERNAME)

    client = DiscuzClient()
    client.load_cookies()

    if not client.is_logged_in():
        logger.error(
            "Cookies missing or expired for user '{}'.\n"
            "  1. Open {} in browser and log in as '{}'.\n"
            "  2. Run: python tools/inject_cookies.py\n"
            "  3. Restart: python main.py",
            settings.DISCUZ_USERNAME,
            settings.DISCUZ_BASE_URL,
            settings.DISCUZ_USERNAME,
        )
        sys.exit(1)

    logger.info("Cookie login verified")

    scanner = Scanner(client=client)
    worker = Worker(client=client)

    logger.info("Running initial scan for forum ids: {}", settings.SCANNER_FORUM_IDS)
    scanner.scan_new_threads()

    last_scan_time: float = 0.0
    last_quote_time: float = 0.0

    while worker.running:
        try:
            now = time.time()
            if now - last_scan_time >= settings.SCANNER_INTERVAL_SECONDS:
                logger.info("Triggering scan_new_threads (elapsed {:.0f}s)", now - last_scan_time)
                scanner.scan_new_threads()
                last_scan_time = now

            if now - last_quote_time >= settings.QUOTE_CHECK_INTERVAL_SECONDS:
                logger.info("Triggering check_quotes (elapsed {:.0f}s)", now - last_quote_time)
                scanner.check_quotes()
                last_quote_time = now

            job = worker.run_once()
            if not job:
                time.sleep(settings.WORKER_SLEEP_SECONDS)
        except KeyboardInterrupt:
            logger.info("Agent stopped by user")
            worker.running = False
        except Exception as e:
            logger.error("Main loop error: {}", e)
            time.sleep(settings.WORKER_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
