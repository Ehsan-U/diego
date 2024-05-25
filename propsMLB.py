import base64
import io
import os
import re
import shutil
import time
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
logger.setLevel(logging.INFO)

_date = input("Date: ") # 2024-05-24


class WebDriver:
    """ Common usage of playwright"""
    ad_domains = ["googlesyndication.com", "googletagmanager.com"]
    solver = TwoCaptcha('a')


    def __init__(self, headless: bool = True, user_data_dir: str = "./program-data", timeout: int = 30000, channel: str = None):
        self.play = sync_playwright().start()
        self.browser = self.play.chromium.launch_persistent_context(headless=headless, user_data_dir=user_data_dir, channel=channel, ignore_https_errors=True)
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


    def csv_handler(self, route: Route):
        logger.debug("Intercepted CSV response")
        response = route.fetch()
        self.captured_df = pd.read_csv(io.StringIO(response.text()))
        route.abort()


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

    def __init__(self, filename: str):
        mode = 'w' if not os.path.exists(filename) else 'a'
        self.writer = pd.ExcelWriter(filename, engine="openpyxl", mode=mode, if_sheet_exists="replace")  if mode == "a" else pd.ExcelWriter(filename, engine="openpyxl", mode=mode)

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



#####################################################


class FanGraph:
    lhh_url = "https://www.fangraphs.com/leaders/major-league?pos=all&lg=all&qual=0&season=2024&season1=2024&ind=0&rost=0&filter=&players=0&team=0&stats=pit&type=0&month=13&pageitems=2000000000&sortcol=2&sortdir=default&pagenum=1"
    rhh_url = "https://www.fangraphs.com/leaders/major-league?pos=all&lg=all&qual=0&season=2024&season1=2024&ind=0&rost=0&filter=&players=0&team=0&stats=pit&pageitems=2000000000&sortcol=2&sortdir=default&type=0&month=14"
    lhp_url = "https://www.fangraphs.com/leaders/major-league?lg=all&qual=0&season=2024&season1=2024&ind=0&rost=0&filter=&players=0&team=0&stats=bat&pageitems=2000000000&pos=np&type=8&month=13"
    rhp_url = "https://www.fangraphs.com/leaders/major-league?lg=all&qual=0&season=2024&season1=2024&ind=0&rost=0&filter=&players=0&team=0&stats=bat&pageitems=2000000000&pos=np&type=8&month=14"
    last_7_url = 'https://www.fangraphs.com/leaders/major-league?lg=all&qual=0&season=2024&season1=2024&ind=0&rost=0&filter=&players=0&team=0&stats=bat&pageitems=2000000000&pos=np&type=8&month=1'


    def __init__(self, driver: WebDriver, exporter: FeedExporter):
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__


    def parse_stats_page(self, response: str):
        items = []
        if not response:
            return items
        try:
            sel = Selector(text=response)
            table = sel.xpath("//div[contains(@class, 'leaders-major_leaders-major')]//div[@class='table-scroll']/table")
            for row in table.xpath("./tbody/tr"):
                item = {}
                for td in row.xpath("./td"):
                    if td.xpath("./a/text()").get():
                        header = td.xpath('./@data-stat').get()
                        if header in item:
                            header += "_2"
                        item[header] = td.xpath("./a/text()").get('TBD').strip()
                    else:
                        header = td.xpath('./@data-stat').get()
                        if header in item:
                            header += "_2"
                        item[header] = td.xpath("./text()").get('TBD').strip()
                items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.parse_ml_stats_page.__name__} [{self.spider}]")
        return items


    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        
        lhh_page = self.driver.get_page(
            url=self.lhh_url,
            wait_selector="//div[contains(@class, 'leaders-major_leaders-major')]//div[@class='table-scroll']/table",
            wait_timeout=10000
        )
        rhh_page = self.driver.get_page(
            url=self.rhh_url,
            wait_selector="//div[contains(@class, 'leaders-major_leaders-major')]//div[@class='table-scroll']/table",
            wait_timeout=10000
        )
        lhp_page = self.driver.get_page(
            url=self.lhp_url,
            wait_selector="//div[contains(@class, 'leaders-major_leaders-major')]//div[@class='table-scroll']/table",
            wait_timeout=10000
        )
        rhp_page = self.driver.get_page(
            url=self.rhp_url,
            wait_selector="//div[contains(@class, 'leaders-major_leaders-major')]//div[@class='table-scroll']/table",
            wait_timeout=10000
        )
        last_7_page = self.driver.get_page(
            url=self.last_7_url,
            wait_selector="//div[contains(@class, 'leaders-major_leaders-major')]//div[@class='table-scroll']/table",
            wait_timeout=10000
        )
        lhh_item = self.parse_stats_page(lhh_page)
        rhh_item = self.parse_stats_page(rhh_page)
        lhp_item = self.parse_stats_page(lhp_page)
        rhp_item = self.parse_stats_page(rhp_page)
        last_7_item = self.parse_stats_page(last_7_page)
        datas.append((lhh_item, "FgLHP"))
        datas.append((rhh_item, "FgRHP"))
        datas.append((lhp_item, "BvLHP"))
        datas.append((rhp_item, "BvRHP"))
        datas.append((last_7_item, "Last 7"))
        for data, sheet in datas:
            self.exporter.export(data, sheet)


##########


class BallParker:
    matchups_url = "https://www.ballparkpal.com/Matchups.php?date={}"
    pitchers_url = "https://www.ballparkpal.com/StartingPitchers.php?date={}"
    hits_url = "https://www.ballparkpal.com/PlayerProps.php?date={}&BetSide=1&BetMarket=13"
    total_bases_url = "https://www.ballparkpal.com/PlayerProps.php?date={}&BetSide=1&BetMarket=14"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.driver.page.route("**/*.csv", self.driver.csv_handler)
        self.exporter = exporter
        self.spider = self.__class__.__name__

    
    def login(self):
        url = "https://www.ballparkpal.com/login.php"
        try:
            self.driver.get_page(url)
            self.driver.page.fill("//input[@name='email']", "diego.lomanto+bpp@gmail.com")       
            self.driver.page.fill("//input[@name='password']", "5Zw^.y1Q{4cx")       
            self.driver.page.click("//input[@name='login']")   
            self.driver.wait_for_selector("//input[@name='login']", state="detached", timeout=5*1000)
            logger.debug("logged in")
            return True
        except Exception as e: 
            logger.error(e)
            logger.debug("error in login")
            return False


    def get_matchups(self):
        url = self.matchups_url.format(_date)
        self.driver.get_page(url)
        try:
            with self.driver.page.expect_download() as download_file:
                self.driver.page.click("//span[text()='Excel']/parent::button")
            download_file.value.save_as("matchups_export.xlsx")
            self.driver.page.wait_for_timeout(2*1000)
            df = pd.read_excel("matchups_export.xlsx", header=1)
            os.remove("matchups_export.xlsx")
            return df.to_dict(orient="records")
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_matchups.__name__} [{self.spider}]")
            return []
    

    def get_pitchers(self):
        url = self.pitchers_url.format(_date)
        self.driver.get_page(url)
        try:
            with self.driver.page.expect_download() as download_file:
                self.driver.page.click("//span[text()='Excel']/parent::button")
            download_file.value.save_as("pitchers_export.xlsx")
            self.driver.page.wait_for_timeout(2*1000)
            df = pd.read_excel("pitchers_export.xlsx", header=1)
            os.remove("pitchers_export.xlsx")
            return df.to_dict(orient="records")
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_pitchers.__name__} [{self.spider}]")
            return []
        

    def get_hits(self):
        items = []
        url = self.hits_url.format(_date)
        response = self.driver.get_page(url)
        try:
            selector = Selector(response)
            headers = selector.xpath("//table[@id='table_id']/thead/tr/th/text()").getall()
            for row in selector.xpath("//table[@id='table_id']/tbody/tr"):
                cells = [t for t in row.xpath("./td//text()").getall() if t.strip()]
                item = {}
                for header, val in zip(headers, cells):
                    if header in item:
                        header += "_2"
                    item[header] = val
                items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_hits.__name__} [{self.spider}]")
        finally:
            return items


    def get_total_bases(self):
        items = []
        url = self.total_bases_url.format(_date)
        response = self.driver.get_page(url)
        try:
            selector = Selector(response)
            headers = selector.xpath("//table[@id='table_id']/thead/tr/th/text()").getall()
            for row in selector.xpath("//table[@id='table_id']/tbody/tr"):
                cells = [t for t in row.xpath("./td//text()").getall() if t.strip()]
                item = {}
                for header, val in zip(headers, cells):
                    if header in item:
                        header += "_2"
                    item[header] = val
                items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_total_bases.__name__} [{self.spider}]")
        finally:
            return items


    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            matchups = self.get_matchups()
            pitchers = self.get_pitchers()
            hits = self.get_hits()
            total_bases = self.get_total_bases()
            datas.append((matchups, "BPMatchups"))
            datas.append((pitchers, "BPpitchers"))
            datas.append((hits, "BPHits"))
            datas.append((total_bases, "BPTB"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)

##########


class Paydirt:
    url = "https://paydirtdfs.com/mlb-paywalled/mlb-game-betting-model/"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__


    def login(self):
        try:
            response = self.driver.get_page("https://paydirtdfs.com/login/", wait_selector="//input[@id='user_login']")
            if not is_exist(response, "//input[@id='user_login']"):
                raise TimeoutError("Already logged in")
            self.driver.page.locator("//input[@id='user_login']").fill("TPERFB")
            self.driver.page.wait_for_timeout(1000)
            self.driver.page.locator("//input[@id='user_pass']").fill("testing_password_111")
            self.driver.page.wait_for_timeout(1000)
            self.driver.page.locator("//input[@id='rememberme']").check()
            self.driver.page.wait_for_timeout(1000)
            self.driver.page.locator("//input[@id='wp-submit']").click()
            self.driver.wait_for_selector("//input[@id='wp-submit']", state="hidden")
            logger.debug("logged in")
            return True
        except TimeoutError as e:
            # logger.debug(e)
            return True
        except Exception as e:
            logger.debug("error in login")
            logger.error(e)
            return False
        

    def get_paydirt(self):
        self.driver.get_page(self.url, wait_selector="//iframe")
        try:
            iframe = self.driver.page.frames[1]
            self.driver.wait_for_selector(iframe=iframe, selector="//p[contains(text(), 'Export Team Model')]/ancestor::button")
            with self.driver.page.expect_download() as download_file:
                iframe.click("//p[contains(text(), 'Export Team Model')]/ancestor::button")
            filepath = download_file.value.path()
            shutil.copy(filepath, "paydirt.csv")
            df = pd.read_csv("paydirt.csv")
            os.remove("paydirt.csv")
            return df.to_dict(orient="records")
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_paydirt.__name__} [{self.spider}]")
            
    
    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            mlb_paydirt = self.get_paydirt()
            datas.append((mlb_paydirt, "PD Batters"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)


##########


class PropsCash:
    url = "https://www.props.cash/"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__


    def login(self):
        try:
            response = self.driver.get_page("https://www.props.cash/login", wait_selector="//input[@type='email']")
            if not is_exist(response, "//input[@type='email']"):
                raise TimeoutError("Already logged in")
            self.driver.page.locator("//input[@type='email']").fill("diego.lomanto+props@gmail.com")
            self.driver.page.wait_for_timeout(1000)
            self.driver.page.locator("//input[@name='password']").fill("93INrKx^6e1.")
            self.driver.page.wait_for_timeout(1000)
            if is_exist(response, "//div[@class='auth0-lock-captcha']"):
                logger.info("solving captcha")
                code = self.driver.solve_captcha(response)
                self.driver.page.fill("//input[@id='1-captcha']", code)
            self.driver.page.locator("//button[@name='submit']").click()
            self.driver.page.wait_for_selector("//button[@name='submit']", state="hidden")
            logger.debug("logged in")
            return True
        except TimeoutError as e:
            # logger.debug(e)
            return True
        except Exception as e:
            logger.error(e)
            logger.debug("error in login")
            return False


    def parse(self, response: str):
        items = []
        if not response:
            return items
        sel = Selector(response)
        headers = sel.xpath("//table/thead/tr/th//text()").getall()
        for row in sel.xpath("//table/tbody/tr"):
            item = {}
            for header, col in zip(headers, row.xpath("./td")):
                item[header] = "".join(col.xpath(".//text()[string-length(.) > 0]").getall()).strip()
            items.append(item)
        return items


    def get_pchits(self):
        try:
            dropdown = self.driver.page.locator("//select[@id='mlb-prop']").all()[1]
            dropdown.select_option("hits")
            self.driver.page.wait_for_timeout(2*1000)
            response = self.driver.page.content()
            return self.parse(response)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_pchits.__name__} [{self.spider}]")
            return []
        
    
    def get_pctb(self):
        try:
            dropdown = self.driver.page.locator("//select[@id='mlb-prop']").all()[1]
            dropdown.select_option("totalBases")
            self.driver.page.wait_for_timeout(2*1000)
            response = self.driver.page.content()
            return self.parse(response)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_pctb.__name__} [{self.spider}]")
            return []


    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            self.driver.get_page(self.url, wait_selector="//table/tbody/tr", callback=self.driver.click, selector='//div[text()="MLB"]')
            pchits = self.get_pchits()
            pctb = self.get_pctb()
            datas.append((pchits, "PcHits"))
            datas.append((pctb, "PCTB"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)


##########

class EvAnalystics:
    hits_url = "https://evanalytics.com/mlb/models/players"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__

    
    def login(self):
        try:
            response = self.driver.get_page("https://evanalytics.com/login")
            sel = Selector(text=response)
            if sel.xpath("//form[@id='formy']"):
                logger.info("Logging in")
                self.driver.page.wait_for_selector("//form[@id='formy']")
                self.driver.page.locator("//input[@name='username']").fill("diego.lomanto@gmail.com")
                self.driver.page.locator("//input[@name='pwd']").fill("D!g5n8!Txqav!SM")
                self.driver.page.locator("//input[@name='remember']").check()
                self.driver.page.locator("//button").click()
            logger.debug("logged in")
            return True
        except Exception as e:
            logger.error(e)
            logger.debug("Error while login")
            return False
    

    def parse_hits(self, response: str):
        items = []
        if not response:
            return items
        try:
            selector = Selector(response)
            headers = [" ".join(th.xpath("./text()").getall()) for th in selector.xpath("//table[@id='dataTable']/thead/tr/th")]
            for row in selector.xpath("//table[@id='dataTable']/tbody/tr"):
                cells = [t.xpath("./text()").get("") for t in row.xpath("./td")]
                item = {}
                for header, val in zip(headers, cells):
                    if header in item:
                        header += "_2"
                    item[header] = val
                items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.parse_hits.__name__} [{self.spider}]")
        finally:
            return items


    def get_hits(self):
        try:
            self.driver.get_page(self.hits_url, wait_selector="//button[@data-val='DRAFTKINGS']")
            self.driver.click("//button[@data-val='DRAFTKINGS' and @class='group-button']", wait_after=5*1000)
            self.driver.click("//button[@data-val='H' and @class='group-button']", wait_after=5*1000)
            self.driver.click("//button[@data-val='R' and @class='group-button']", wait_after=5*1000)
            self.driver.click("//button[@data-val='RBI' and @class='group-button']", wait_after=5*1000)
            self.driver.click("//div[contains(text(), 'MARKET')]/button[@data-val='TB' and @class='group-button']", wait_after=5*1000)
            response = self.driver.page.content()
            return self.parse_hits(response)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_hits.__name__} [{self.spider}]")


    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            hits = self.get_hits()
            datas.append((hits, "EVhits"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)


##########



driver = WebDriver(timeout=60*1000, headless=True)
exporter = FeedExporter(filename="workbook.xlsx")

spiders = [
    FanGraph(driver, exporter),
    BallParker(driver, exporter),
    Paydirt(driver, exporter),
    PropsCash(driver, exporter),
    EvAnalystics(driver, exporter)
]
try:
    for spider in spiders:
        spider.crawl()
except (Exception, KeyboardInterrupt):
    pass
driver.close()
exporter.close()