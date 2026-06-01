import re
from html import escape
from html.parser import HTMLParser


ALLOWED_SIMPLE_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "code",
    "pre",
    "blockquote",
}


class TelegramHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tg-emoji":
            return
        if tag in ALLOWED_SIMPLE_TAGS:
            self.parts.append(f"<{tag}>")
            self.stack.append(tag)
            return
        if tag == "a":
            href = ""
            for key, value in attrs:
                if key.lower() == "href":
                    href = value or ""
                    break
            if href.startswith(("http://", "https://", "tg://")):
                self.parts.append(f'<a href="{escape(href, quote=True)}">')
                self.stack.append(tag)
                return
        self.parts.append(escape(self.get_starttag_text() or "", quote=False))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "tg-emoji":
            return
        if tag in self.stack:
            while self.stack:
                open_tag = self.stack.pop()
                self.parts.append(f"</{open_tag}>")
                if open_tag == tag:
                    break
            return
        self.parts.append(escape(f"</{tag}>", quote=False))

    def handle_data(self, data):
        self.parts.append(escape(data, quote=False))

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def get_html(self) -> str:
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts)


def sanitize_telegram_html(text: str) -> str:
    text = re.sub(r"</?\s*tg-emoji\b[^>]*>", "", text or "", flags=re.IGNORECASE)
    parser = TelegramHTMLSanitizer()
    try:
        parser.feed(text or "")
        parser.close()
        return parser.get_html()
    except Exception:
        return escape(text or "", quote=False)


def normalize_ai_output_html(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text or "", flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<u>\1</u>", text, flags=re.DOTALL)
    return sanitize_telegram_html(text)


def html_message(title: str, body: str) -> str:
    return f"<b>{escape(title, quote=False)}</b>\n\n{sanitize_telegram_html(body)}"
