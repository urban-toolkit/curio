import os
import re
import json
import time
from contextlib import contextmanager
from typing import ContextManager

from playwright.sync_api import Locator, Page, expect

# #region agent log
# Repo root is 4 levels up: test_frontend -> tests -> backend -> utk_curio -> curio-main
_DEBUG_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", ".curio", "playwright.log"
)
def _dlog(location, message, data=None, hypothesis_id=""):
    try:
        entry = {"timestamp": int(time.time()*1000), "location": location, "message": message, "data": data or {}, "hypothesisId": hypothesis_id}
        with open(_DEBUG_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
# #endregion


class FrontendPage(Page):
    def __init__(self, frontend_server: str, page: Page):  # noqa
        # #region agent log
        _dlog("utils.py:FrontendPage.__init__", "FrontendPage created", {"frontend_server": frontend_server, "page_type": type(page).__name__, "page_url": str(page.url), "page_is_closed": page.is_closed()}, "H1,H2,H3")
        # #endregion
        self.frontend_server = frontend_server
        self.page = page
        self.browser_context = page.context

    def set_language(self, language="en-US"):
        self.browser_context.set_extra_http_headers({"Accept-Language": language})

    def goto_page(self, path):
        # #region agent log
        url = f"{self.frontend_server}{path}"
        _dlog("utils.py:goto_page", "About to navigate", {"url": url, "page_is_closed": self.page.is_closed(), "page_url": str(self.page.url), "has_impl_obj": hasattr(self, '_impl_obj')}, "H2,H3,H5")
        # #endregion
        try:
            result = self.page.goto(f"{self.frontend_server}{path}")
            # #region agent log
            _dlog("utils.py:goto_page", "Navigation succeeded", {"url": url, "result_status": result.status if result else None}, "H2,H4")
            # #endregion
            return result
        except Exception as e:
            # #region agent log
            _dlog("utils.py:goto_page", "Navigation FAILED", {"url": url, "error_type": type(e).__name__, "error_msg": str(e)[:500]}, "H1,H2,H3,H4,H5")
            # #endregion
            raise

    def expect_url(self, url: str):
        self.page.expect_navigation(url=url)
        self.page.wait_for_url(url)

    def expect_page_title(self, search_title: str):
        expect(self.page).to_have_title(re.compile(search_title))

