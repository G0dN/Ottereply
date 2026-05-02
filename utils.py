import re
import unicodedata


def sanitize_reply(text: str, max_length: int = 1000) -> str:
    text = text.strip()
    text = text[:max_length]
    text = unicodedata.normalize("NFKC", text)
    return text


def remove_html_tags(text: str) -> str:
    return re.sub(r"<[^>]*>", "", text)


def has_html(text: str) -> bool:
    return bool(re.search(r"<[^>]*>", text))


def clean_html(text: str) -> str:
    text = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]*>", "", text)
    return text
