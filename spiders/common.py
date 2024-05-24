import base64
import io
import re
from parsel import Selector
from playwright.sync_api import sync_playwright, Route, Frame
from twocaptcha import TwoCaptcha
import pandas as pd
from typing import Dict, List
import logging
from PIL import Image
import cairosvg
logging.basicConfig(level=logging.WARNING,
    format='=> %(levelname)s - %(module)s - %(asctime)s - %(message)s',
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
    ])

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)



class WebDriver:
    """ Common usage of playwright"""
    ad_domains = ["googlesyndication.com", "googletagmanager.com"]
    solver = TwoCaptcha('ab7f903d21bf75ea49dc155c5bf34fda')


    def __init__(self, headless: bool = True, user_data_dir: str = "./program-data", timeout: int = 30000, channel: str = None):
        self.play = sync_playwright().start()
        self.browser = self.play.chromium.launch_persistent_context(headless=headless, user_data_dir=user_data_dir, channel=channel)
        self.page = self.browser.pages[0]
        self.page.route("**/*", lambda route: route.abort() if any([domain for domain in self.ad_domains if domain in route.request.url]) else route.continue_())
        self.timeout = timeout


    def solve_captcha(self, response):
        sel = Selector(response)
        image_content = re.search(r'base64,(.*)', sel.xpath("//div[@class='auth0-lock-captcha']/div/@style").get()).group(1)[:-3]
        decoded_data = base64.b64decode(image_content).decode('utf-8')
        png_image = cairosvg.svg2png(bytestring=decoded_data)
        image = Image.open(io.BytesIO(png_image))
        image.save("captcha.png")
        result = self.solver.normal('captcha.png', numeric=4, caseSensitive=True, minLength=6, maxLength=6, lang="en")
        return result.get("code")


    def click(self, selector: str, timeout: int = None, wait_after: int = None):
        try:
            timeout = self.timeout if timeout is None else timeout
            self.page.click(selector, timeout=timeout)
            if wait_after is not None:
                self.page.wait_for_timeout(wait_after)
        except Exception as e:
            logger.debug(e)
            logger.debug(f"Error while executing action {self.click.__name__}")
        else:
            logger.debug(f"Action {self.click.__name__} successfully executed")


    def wait_for_selector(self, selector: str, timeout: int = None, state: str = "visible", iframe: Frame = None) -> None:
        try:
            timeout = self.timeout if timeout is None else timeout
            if iframe is None:
                self.page.wait_for_selector(selector, timeout=timeout, state=state)
            else:
                iframe.wait_for_selector(selector, timeout=timeout, state=state)
        except Exception as e:
            logger.debug(e)
            logger.debug(f"Error while executing action {self.wait_for_selector.__name__}")
        else:
            logger.debug(f"Action {self.wait_for_selector.__name__} successfully executed")


    def get_page(self, url: str, wait_selector: str = None, timeout: int = None, wait_timeout: int = 0, callback: callable = None, **kwargs) -> str:
        try:
            timeout = self.timeout if timeout is None else timeout
            self.page.goto(url, timeout=timeout)
            if wait_selector:
                self.wait_for_selector(wait_selector, timeout)
            if wait_timeout:
                self.page.wait_for_timeout(wait_timeout)
            if callback is not None:
                callback(**kwargs)
                if wait_selector:
                    self.wait_for_selector(wait_selector, timeout)
        except Exception as e:
            logger.debug(e)
            logger.debug(f"Error while executing action {self.get_page.__name__}")
            response = None
        else:
            response = self.page.content()
            logger.debug(f"Action {self.get_page.__name__} successfully executed")
        finally:
            return response


    def close(self):
        if hasattr(self, "browser"):
            try:
                self.browser.close()
            except Exception as e:
                logger.debug(e)
                logger.debug(f"Error while closing browser")
        if hasattr(self, "play"):
            try:
                self.play.stop()
            except Exception as e:
                logger.debug(e)
                logger.debug(f"Error while closing playwright")



class FeedExporter:

    def __init__(self, filename: str = "workbook.xlsx"):
        self.writer = pd.ExcelWriter(filename, engine="openpyxl")

    def export(self, data: List[Dict], sheet: str):
        if not data:
            logger.info("No data available")
            return
        try:
            df = self.to_numbers(pd.DataFrame(data))
            df.to_excel(self.writer, sheet_name=sheet, index=False)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while writing to {sheet}")
        else:
            logger.debug(f"Data written to {sheet}")

    def to_numbers(self, df: pd.DataFrame):
        for col in df.columns:
            try:
                df[col] = df[col].astype(float)
            except Exception:
                pass
        return df

    def close(self):
        try:
            self.writer.close()
        except IndexError as e:
            logger.error(e)
            logger.debug("No sheet to write")



def is_exist(response, e):
    sel = Selector(response)
    return sel.xpath(e)