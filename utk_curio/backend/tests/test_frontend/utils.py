import re
from contextlib import contextmanager
from typing import ContextManager

from playwright.sync_api import Locator, Page, expect


class FrontendPage(Page):
    def __init__(self, frontend_server: str, page: Page):  # noqa
        self.frontend_server = frontend_server
        self.page = page
        self.browser_context = page.context

    def set_language(self, language="en-US"):
        self.browser_context.set_extra_http_headers({"Accept-Language": language})

    def goto_page(self, path):
        return self.page.goto(f"{self.frontend_server}{path}")

    def expect_url(self, url: str):
        self.page.expect_navigation(url=url)
        self.page.wait_for_url(url)

    def expect_page_title(self, search_title: str):
        expect(self.page).to_have_title(re.compile(search_title))

