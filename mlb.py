import base64
import datetime
import io
import os
import re
import shutil
from urllib.parse import urljoin
import dateparser
import requests
from parsel import Selector
from playwright.sync_api import sync_playwright, Route, Frame
from twocaptcha import TwoCaptcha
import pandas as pd
from openpyxl.worksheet.worksheet import Worksheet
from typing import Dict, List
import logging
from PIL import Image
import cairosvg
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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
        image_content = re.search(r'base64,(.*)', sel.xpath("//div[@class='auth0-lock-captcha']/div/@style").get('')).group(1)[:-3]
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


    def exists(self, selector: str, iframe: Frame = None):
        count = 0
        try:
            if iframe is None:
                count = self.page.locator(selector=selector).count()
            else:
                count = iframe.locator(selector=selector).count()
        except Exception as e:
            logger.debug(e)
            logger.debug(f"Error while executing action {self.exists.__name__}")
        else:
            logger.debug(f"Action {self.exists.__name__} successfully executed")
        finally:
            return count > 0


    def click(self, selector: str, timeout: int = None, wait_after: int = None, iframe: Frame = None):
        try:
            timeout = self.timeout if timeout is None else timeout
            if iframe is None:
                self.page.click(selector, timeout=timeout)
            else:
                iframe.click(selector=selector, timeout=timeout)
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


    def get_page(self, url: str, wait_selector: str = None, timeout: int = None, wait_after: int = 0, callback: callable = None, **kwargs) -> str:
        try:
            timeout = self.timeout if timeout is None else timeout
            self.page.goto(url, timeout=timeout)
            if wait_selector:
                self.wait_for_selector(wait_selector, timeout)
            if wait_after:
                self.page.wait_for_timeout(wait_after)
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
        self.writer = pd.ExcelWriter(filename, engine="openpyxl", mode=mode, if_sheet_exists="overlay")  if mode == "a" else pd.ExcelWriter(filename, engine="openpyxl", mode=mode)

    def have_lookup(self, worksheet: Worksheet):
        for row in worksheet.iter_rows(min_col=1, min_row=1, max_col=2):
            for cell in row:
                if '=vlookup' in str(cell.value).lower():
                    return True
        return False

    def clear_sheet(self, worksheet: Worksheet, lookup_col: bool):
        if worksheet:
            cols = [col[0].value for col in worksheet.columns if (col[0].value != None and not 'https://' in str(col[0].value).lower())]
            min_col = 2 if lookup_col else 1
            for row in worksheet.iter_rows(min_col=min_col, min_row=1, max_col=len(cols)):
                for cell in row:
                    cell.value = None

    def export(self, data: List[Dict], sheet: str):
        if not data:
            logger.info(f"No data available {sheet}")
            return
        try:
            worksheet: Worksheet = self.writer.sheets.get(sheet)
            if worksheet:
                lookup_col = self.have_lookup(worksheet)
                self.clear_sheet(worksheet, lookup_col)
            else:
                lookup_col = False
            filtered_data = []
            for item in data:
                if None in item.keys():
                    item.pop(None)
                filtered_data.append(item)
            df = self.to_numbers(pd.DataFrame(filtered_data))
            df.to_excel(self.writer, startcol=1 if lookup_col else 0, sheet_name=sheet, index=False)
        except Exception as e:
            logger.error(e, exc_info=True)
            logger.debug(f"Error while writing to {sheet}")
        else:
            logger.info(f"Data written to {sheet}")

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




##########################################
# _date = "2024-06-02"


class BallParker:
    simulation_url = "https://ballparkpal.com/GameSimulations.php?date={}"
    pitchers_url = "https://ballparkpal.com/StartingPitchers.php?date={}"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
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
            logger.debug(f"Error while {self.login.__name__} [{self.spider}]")
            return False


    @staticmethod
    def get_percent_value(value, sep: str = None):
        value = value.split(sep) if sep and value else value
        if value and isinstance(value, list):
            for v in value:
                if '%' in v:
                    return v.strip()
        else:
            return value
        

    @staticmethod
    def get_game_total(selector):
        try:
            cell = selector.xpath('.//td[@style="text-align:center; background-color:#3c963e;"]') or selector.xpath(".//td[@style='text-align:center; background-color:#52b354;']")
            if cell:
                cell_value = int(cell.xpath("./text()").get(0))
                current_row_tds = cell.xpath('./parent::tr/td').getall()
                index = current_row_tds.index(cell.get(''))
                above_cell_text = float(cell.xpath(f'./parent::tr/preceding-sibling::tr[1]/th[{index + 1}]/font/text()').get(0))
                if cell_value < 0:
                    above_cell_text += (abs(cell_value + 100)/5)/10
                elif cell_value > 0:
                    above_cell_text -= (abs(cell_value - 100)/5)/10
                return above_cell_text
        except Exception as e:
            pass


    def get_simulation(self):
        items = []
        try:
            response = self.driver.get_page(self.simulation_url.format(_date), wait_after=2*1000)
            selector = Selector(response)
            for _match in selector.xpath("//div[@style='width: 100vw;']"):
                for variation in [1,2]:
                    item = {
                        "Team": _match.xpath("./div[4]/div/text()").get('').strip() if variation == 1 else _match.xpath("./div[6]/div/text()").get('').strip(),
                        "Pitcher": "".join(_match.xpath("./div[7]/div//text()").getall()).strip() if variation == 1 else "".join(_match.xpath("./div[9]/div//text()").getall()).strip(),
                        "Team Total": _match.xpath("./div[10]/div//text()").get('').strip() if variation == 1 else _match.xpath("./div[12]/div//text()").get('').strip(),
                        "Win %": self.get_percent_value(
                            (lambda: _match.xpath("./div[13]/div//text()").get('').strip() if variation == 1 else _match.xpath("./div[15]/div//text()").get('').strip())()
                        ),
                        "Game Total": self.get_game_total(_match),
                        "F5 Runs": _match.xpath("./div[19]/div//text()").get('').strip() if variation == 1 else _match.xpath("./div[21]/div//text()").get('').strip(),
                        "F5 Lead": self.get_percent_value(
                            (lambda: _match.xpath("./div[22]/div//text()").get('').strip() if variation == 1 else _match.xpath("./div[24]/div//text()").get('').strip())(),
                            sep=" "
                        ),
                        "YRFI": self.get_percent_value(
                            _match.xpath(".//div[@class='yrfi' and contains(text(), 'YRFI')]/text()").get('').strip(),
                            sep=" "
                        ),
                        "Park": _match.xpath(".//a[contains(@href, 'Park')]/text()").get('').strip(),
                        "Runs": _match.xpath(".//a[contains(@href, 'Park')]/following-sibling::text()").get('').split(":")[-1].strip(),
                        "Lineups Final": _match.xpath(".//div[contains(text(), 'Lineups')]/text()").get('').split(":")[-1].strip()
                    }
                    items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_simulation.__name__} [{self.spider}]")
        finally:
            return items


    def get_pitchers(self):
        items = []
        try:
            response = self.driver.get_page(self.pitchers_url.format(_date), wait_after=2*1000)
            selector = Selector(response)
            headers = selector.xpath("//table[@id='table_id']/thead/tr/th/text()").getall()[:12]
            for row in selector.xpath("//table[@id='table_id']/tbody/tr"):
                cells = [t for t in row.xpath("./td//text()").getall() if t.strip()][:12]
                item = {}
                for header, val in zip(headers, cells):
                    if header in item:
                        header += "_2"
                    item[header] = val
                items.append(item)
        except Exception as e:
            logger.info(e)
            logger.debug(f"Error while {self.get_pitchers.__name__} [{self.spider}]")
        finally:
            return items


    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            simulation = self.get_simulation()
            pitchers = self.get_pitchers()
            datas.append((simulation, "BPP"))
            datas.append((pitchers, "PitchData"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)


###########################


class ActionNetwork:
    odds_url = "https://www.actionnetwork.com/mlb/odds"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__


    def login(self):
        try:
            response = self.driver.get_page("https://www.actionnetwork.com/login", wait_after=5*1000)
            if not is_exist(response, "//button[@id='login-submit']"):
                raise TimeoutError("Already logged in")
            self.driver.page.locator("//input[@id='email']").fill("diego.lomanto+AL@gmail.com")
            self.driver.page.wait_for_timeout(1*1000)
            self.driver.page.locator("//input[@id='password']").fill("dy04rR9rL5m3")
            self.driver.page.wait_for_timeout(1000)
            self.driver.click("//button[@id='login-submit']")
            self.driver.wait_for_selector("//button[@id='login-submit']", state="hidden")
            logger.debug("logged in")
            return True
        except TimeoutError:
            return True
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.login.__name__} [{self.spider}]")
            return False


    def find_date(self):
        while True:
            self.driver.page.wait_for_timeout(5000)
            content = self.driver.page.content()
            page_date = (lambda v: datetime.datetime.strptime(v + f" {datetime.datetime.now().year}", "%a %b %d %Y"))(Selector(text=content).xpath("//span[@class='day-nav__display']/text()").get())
            if page_date != self.user_date:
                logger.debug("date not found")
                # decide to move forward or backward
                if page_date > self.user_date:
                    self.driver.click("//button[@aria-label='Previous Date']", timeout=10*1000)
                    logger.debug("going into past")
                else:
                    self.driver.click("//button[@aria-label='Next Date']", timeout=10*1000)
                    logger.debug("going into future")
            else:
                logger.debug("date found")
                break
    

    def scroll_into_view(self, element):
        self.driver.page.locator(element).hover()
        # down
        for i in range(90):
            self.driver.page.mouse.wheel(0,i)
        self.driver.page.wait_for_timeout(1000)
        # up
        for i in range(90):
            self.driver.page.mouse.wheel(0,-i)
        self.driver.page.wait_for_timeout(1000)


    def get_moneyline(self):
        items = []
        try:
            self.driver.click("//div[@class='modal__close']", wait_after=1*1000, timeout=10*1000)
            self.driver.click("//div[@class='odds-tools-sub-nav__desktop-filter']")
            self.driver.page.locator("//div[@data-testid='advanced-filters__location-dropdown']/select").select_option(value="NY")
            self.find_date()
            self.scroll_into_view("//div[@class='best-odds__table-container']")
            response = self.driver.page.content()
            sel = Selector(text=response)
            for row in sel.xpath("//table/tbody/tr[position() mod 2 = 1]"):
                items.append({
                    "Team": row.xpath("./td[1]//div[@class='game-info__teams'][1]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Best Odds": row.xpath("./td[3]/div/div[1]/div/span[1]/text()").get(),
                    "Book": row.xpath("./td[3]/div/div[1]/div/span[2]//img/@alt").get()
                })
                items.append({
                    "Team": row.xpath("./td[1]//div[@class='game-info__teams'][2]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Best Odds": row.xpath("./td[3]/div/div[2]/div/span[1]/text()").get(),
                    "Book": row.xpath("./td[3]/div/div[2]/div/span[2]//img/@alt").get()
                })
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_moneyline.__name__} [{self.spider}]")
        finally:
            return items


    def get_total(self):
        items = []
        try:
            self.driver.page.locator("//div[@data-testid='odds-tools-sub-nav__odds-type']/select").select_option(value="total")
            self.driver.page.wait_for_timeout(5*1000)
            self.scroll_into_view("//div[@class='best-odds__table-container']")
            response = self.driver.page.content()
            sel = Selector(text=response)
            for row in sel.xpath("//table/tbody/tr[position() mod 2 = 1]"):
                items.append({
                    "Team": row.xpath("./td[1]//div[@class='game-info__teams'][1]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Over/Under": 'o' if 'o' in row.xpath("./td[3]/div/div[1]/div/span[1]/text()").get('') else 'u',
                    "Total": row.xpath("./td[3]/div/div[1]/div/span[1]/text()").get('').replace("o",'').replace("u",''),
                    "Best Odds": row.xpath("./td[3]/div/div[1]/div/span[2]/text()").get(),
                    "Book": row.xpath("./td[3]/div/div[1]/div/span[3]//img/@alt").get()
                })
                items.append({
                    "Team": row.xpath("./td[1]//div[@class='game-info__teams'][2]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Over/Under": 'o' if 'o' in row.xpath("./td[3]/div/div[2]/div/span[1]/text()").get() else 'u',
                    "Total": row.xpath("./td[3]/div/div[2]/div/span[1]/text()").get('').replace("o",'').replace("u",''),
                    "Best Odds": row.xpath("./td[3]/div/div[2]/div/span[2]/text()").get(),
                    "Book": row.xpath("./td[3]/div/div[2]/div/span[3]//img/@alt").get()
                })
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_total.__name__} [{self.spider}]")
        finally:
            return items
    

    def get_f5(self):
        items = []
        try:
            self.driver.page.locator("//div[@data-testid='odds-tools__dropdown']/select").select_option(value="firstfiveinnings")
            self.driver.page.wait_for_timeout(5000)
            self.scroll_into_view("//div[@class='best-odds__table-container']")
            response = self.driver.page.content()
            sel = Selector(text=response)
            for row in sel.xpath("//table/tbody/tr[position() mod 2 = 1]"):
                items.append({
                    "Team": row.xpath("./td[1]//div[@class='game-info__teams'][1]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Best Odds": row.xpath("./td[3]/div/div[1]/div/span[2]/text()").get(),
                    "Book": row.xpath("./td[3]/div/div[1]/div/span[3]//img/@alt").get()
                })
                items.append({
                    "Team": row.xpath("./td[1]//div[@class='game-info__teams'][2]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Best Odds": row.xpath("./td[3]/div/div[2]/div/span[2]/text()").get(),
                    "Book": row.xpath("./td[3]/div/div[2]/div/span[3]//img/@alt").get()
                })
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_f5.__name__} [{self.spider}]")
        finally:
            return items
        
    
    def get_projection_ml(self):
        items = []
        try:
            self.driver.get_page("https://www.actionnetwork.com/mlb/projections")
            self.find_date()
            self.scroll_into_view("//div[@class='projections__table-container']")
            response = self.driver.page.content()
            sel = Selector(text=response)
            for row in sel.xpath("//table/tbody/tr"):
                team1 = {
                    "Team": row.xpath("./td[1]/div/a/div[1]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Open": row.xpath("./td[2]/div/div[1]/text()").get(),
                    "Pro-Line": row.xpath("./td[3]/div/div[1]/text()").get('').replace('o','').replace('u',''),
                    "Cons": row.xpath("./td[4]/div/div[1]/text()").get(),
                    "Grade": row.xpath("./td[5]/div/div[1]/div/text()").get(),
                    "Edge": row.xpath("./td[6]/div/div[1]/div/text()").get(),
                    "Best Odds": row.xpath("./td[7]/div/div[1]/div/span/text()").get(),
                    "Bet %": row.xpath("./td[8]/div/span[1]/span/span/text()").get(),
                    "Money %": row.xpath("./td[9]/div/span[1]/div/text()").get()
                }
                team2 = {
                    "Team": row.xpath("./td[1]/div/a/div[2]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Open": row.xpath("./td[2]/div/div[2]/text()").get(),
                    "Pro-Line": row.xpath("./td[3]/div/div[2]/text()").get('').replace('o','').replace('u',''),
                    "Cons": row.xpath("./td[4]/div/div[2]/text()").get(),
                    "Grade": row.xpath("./td[5]/div/div[2]/div/text()").get(),
                    "Edge": row.xpath("./td[6]/div/div[2]/div/text()").get(),
                    "Best Odds": row.xpath("./td[7]/div/div[2]/div/span/text()").get(),
                    "Bet %": row.xpath("./td[8]/div/span[2]/span/span/text()").get(),
                    "Money %": row.xpath("./td[9]/div/span[2]/div/text()").get()
                }
                items.append(team1)
                items.append(team2)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_projection_ml.__name__} [{self.spider}]")
        finally:
            return items
        

    def get_projection_total(self):
        items = []
        try:
            self.driver.page.locator("//div[@data-testid='odds-tools-sub-nav__odds-type']/select").select_option(value="total")
            self.driver.page.wait_for_timeout(5000)
            self.scroll_into_view("//div[@class='projections__table-container']")
            response = self.driver.page.content()
            sel = Selector(text=response)
            for row in sel.xpath("//table/tbody/tr"):
                team1 = {
                    "Team": row.xpath("./td[1]/div/a/div[1]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Open": row.xpath("./td[2]/div/div[1]/text()").get(),
                    "Pro-Line": row.xpath("./td[3]/div/div[1]/text()").get('').replace('o','').replace('u',''),
                    "Cons": row.xpath("./td[4]/div/div[1]/text()").get(),
                    "Grade": row.xpath("./td[5]/div/div[1]/div/text()").get(),
                    "Edge": row.xpath("./td[6]/div/div[1]/div/text()").get(),
                    "Best Odds": row.xpath("./td[7]/div/div[1]/div/span/text()").get(),
                    "Bet %": row.xpath("./td[8]/div/span[1]/span/span/text()").get(),
                    "Money %": row.xpath("./td[9]/div/span[1]/div/text()").get()
                }
                team2 = {
                    "Team": row.xpath("./td[1]/div/a/div[2]//div[@class='game-info__team--desktop']/span/text()").get(),
                    "Open": row.xpath("./td[2]/div/div[2]/text()").get(),
                    "Pro-Line": row.xpath("./td[3]/div/div[2]/text()").get('').replace('o','').replace('u',''),
                    "Cons": row.xpath("./td[4]/div/div[2]/text()").get(),
                    "Grade": row.xpath("./td[5]/div/div[2]/div/text()").get(),
                    "Edge": row.xpath("./td[6]/div/div[2]/div/text()").get(),
                    "Best Odds": row.xpath("./td[7]/div/div[2]/div/span/text()").get(),
                    "Bet %": row.xpath("./td[8]/div/span[2]/span/span/text()").get(),
                    "Money %": row.xpath("./td[9]/div/span[2]/div/text()").get()
                }
                items.append(team1)
                items.append(team2)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_projection_total.__name__} [{self.spider}]")
        finally:
            return items
        
    
    def get_picks(self):
        items = []
        try:
            response = self.driver.get_page("https://www.actionnetwork.com/mlb/picks/latest-picks", wait_selector="//div[@class='picks-container__wrapper']")
            sel = Selector(response)
            author = sel.xpath("//h1[text()='Pending Picks']/parent::div/div[1]//div[@class='pick-card__expert-info']/a/text()").get('').strip().split(" ")[-1]
            for pick in sel.xpath("//h1[text()='Pending Picks']/parent::div/div/div[not(contains(@class, 'pick-card__header'))]"):
                txt = " ".join(pick.xpath(".//div[@class='base-pick__pick-name']//text()").getall())
                team1 = pick.xpath(".//div[@class='base-pick__details']/div/div[1]/text()").get()
                team2 = pick.xpath(".//div[@class='base-pick__details']/div/div[2]/text()").get()
                if 'under' in txt.lower():
                    item = {
                        "Expert": author + " O",
                        "Team": team2,
                        "Pick": txt.replace("Under", "U")
                    }
                elif "over" in txt.lower():
                    item = {
                        "Expert": author + " O",
                        "Team": team1,
                        "Pick": txt.replace("Over", "O"),
                    }
                else:
                    item = {
                        "Expert": author + " ML",
                        "Team": re.search(r'[a-zA-Z\s]+', txt).group() if re.search(r'[a-zA-Z\s]+', txt) else None,
                        "Pick": re.search(r'[\d\s\+\-\.F\(\)]+', txt).group() if re.search(r'[\d\+\-\.]+', txt) else None,
                    }
                items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_picks.__name__} [{self.spider}]")
        finally:
            return items
        

    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            self.user_date = datetime.datetime.strptime(_date, "%Y-%m-%d")
            self.driver.get_page(self.odds_url, wait_after=5*1000)
            moneyline = self.get_moneyline()
            total = self.get_total()
            f5 = self.get_f5()
            projection_ml = self.get_projection_ml()
            projection_total = self.get_projection_total()
            picks = self.get_picks()
            datas.append((moneyline, "Action ML"))
            datas.append((total, "Action Total"))
            datas.append((f5, "Action F5"))
            datas.append((projection_ml, "Projections ML"))
            datas.append((projection_total, "Projections Total"))
            datas.append((picks, "Action Expert"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)


###########################


class EvAnalytics:
    all_url = "https://evanalytics.com/mlb/models/teams/all-markets"
    moneyline_url = "https://evanalytics.com/mlb/models/teams/moneyline"
    advanced_url = "https://evanalytics.com/mlb/models/teams/advanced"
    game_total_url = "https://evanalytics.com/mlb/models/teams/game-total"


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
            logger.debug(f"Error while {self.login.__name__} [{self.spider}]")
            return False
    

    def get_all(self):
        items = []
        try:
            resps = []
            response = self.driver.get_page(self.all_url, wait_selector="//table[@id='dataTable']")
            resps.append(response)
            other_btn = self.driver.exists("//button[not(contains(@class, 'button-clicked')) and contains(@id, 'searchdate')]")
            if other_btn:  # today
                self.driver.click("//button[not(contains(@class, 'button-clicked')) and contains(@id, 'searchdate')]", wait_after=5*1000)
                resps.append(self.driver.page.content())
            for resp in resps:
                sel = Selector(text=resp)
                for row in sel.xpath("//table[@id='dataTable']/tbody/tr"):
                    scraped_date = row.xpath("./td[3]/text()").get('')
                    if scraped_date in _date.replace("-",'/'):
                        item = {
                            "TM": row.xpath("./td[6]/text()").get(),
                            "Date": scraped_date,
                            "Time": row.xpath("./td[4]/text()").get(),
                            "Game": row.xpath("./td[5]/text()").get(),
                            "OL": row.xpath("./td[7]/text()").get(),
                            "O/U Over": row.xpath("./td[8]/text()").get(),
                            "Over W%": row.xpath("./td[9]/text()").get(),
                            "Over EV": row.xpath("./td[10]/text()").get(),
                            "O/U Under": row.xpath("./td[11]/text()").get(),
                            "Under W%": row.xpath("./td[12]/text()").get(),
                            "Under EV": row.xpath("./td[13]/text()").get(),
                            "TT Over": row.xpath("./td[14]/text()").get(),
                            "TT Over W%": row.xpath("./td[15]/text()").get(),
                            "TT Over EV": row.xpath("./td[16]/text()").get(),
                            "TT Under": row.xpath("./td[17]/text()").get(),
                            "TT Under W%": row.xpath("./td[18]/text()").get(),
                            "TT Under EV": row.xpath("./td[19]/text()").get(),
                            "ML": row.xpath("./td[20]/text()").get(),
                            "ML W%": row.xpath("./td[21]/text()").get(),
                            "ML EV": row.xpath("./td[22]/text()").get(),
                            "RL": row.xpath("./td[23]/text()").get(),
                            "RL W%": row.xpath("./td[24]/text()").get(),
                            "RL EV": row.xpath("./td[25]/text()").get(),
                        }
                        items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_all.__name__} [{self.spider}]")
        finally:
            return items
        

    def get_moneyline(self):
        items = []
        try:
            resps = []
            response = self.driver.get_page(self.moneyline_url, wait_selector="//table[@id='dataTable']")
            resps.append(response)
            other_btn = self.driver.exists("//button[not(contains(@class, 'button-clicked')) and contains(@id, 'searchdate')]")
            if other_btn:  # today
                self.driver.click("//button[not(contains(@class, 'button-clicked')) and contains(@id, 'searchdate')]", wait_after=5*1000)
                resps.append(self.driver.page.content())
            for resp in resps:
                sel = Selector(text=resp)
                for row in sel.xpath("//table[@id='dataTable']/tbody/tr"):
                    scraped_date = row.xpath("./td[3]/text()").get('')
                    if scraped_date in _date.replace("-",'/'):
                        item = {
                            "Date": row.xpath("./td[3]/text()").get(),
                            "Time": row.xpath("./td[4]/text()").get(),
                            "Game (GM)": row.xpath("./td[5]/text()").get(),
                            "Team (TM)": row.xpath("./td[6]/text()").get(),
                            "Starting Pitcher (SP)": row.xpath("./td[7]/text()").get(),
                            "Official Lineup (OL)": row.xpath("./td[8]/text()").get(),
                            "Moneyline (ML)": row.xpath("./td[9]/text()").get(),
                            "Win Pct (W%)": row.xpath("./td[10]/text()").get(),
                            "Expected Value (EV)": row.xpath("./td[11]/text()").get(),
                            "Bet %": row.xpath("./td[12]/text()").get(),
                            "Cash %": row.xpath("./td[13]/text()").get(),
                        }
                        items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_moneyline.__name__} [{self.spider}]")
        finally:
            return items
    

    def get_advanced(self):
        items = []
        try:
            resps = []
            response = self.driver.get_page(self.advanced_url, wait_selector="//table[@id='dataTable']")
            resps.append(response)
            other_btn = self.driver.exists("//button[not(contains(@class, 'button-clicked')) and contains(@id, 'searchdate')]")
            if other_btn:  # today
                self.driver.click("//button[not(contains(@class, 'button-clicked')) and contains(@id, 'searchdate')]", wait_after=5*1000)
                resps.append(self.driver.page.content())
            for resp in resps:
                sel = Selector(text=resp)
                for row in sel.xpath("//table[@id='dataTable']/tbody/tr"):
                    scraped_date = row.xpath("./td[3]/text()").get('')
                    if scraped_date in _date.replace("-",'/'):
                        item = {
                            "Time": row.xpath("./td[4]/text()").get(),
                            "Game": row.xpath("./td[5]/text()").get(),
                            "Date": row.xpath("./td[3]/text()").get(),
                            "Team": row.xpath("./td[6]/text()").get(),
                            "OPP SP": row.xpath("./td[7]/text()").get(),
                            "Park": row.xpath("./td[8]/text()").get(),
                            "Ump": row.xpath("./td[9]/text()").get(),
                            "HFA": row.xpath("./td[10]/text()").get(),
                            "OL": row.xpath("./td[11]/text()").get(),
                            "O/U": row.xpath("./td[12]/text()").get(),
                            "vO/U": row.xpath("./td[13]/text()").get(),
                            "O/U Diff": row.xpath("./td[14]/text()").get(),
                            "TT": row.xpath("./td[15]/text()").get(),
                            "vTT": row.xpath("./td[16]/text()").get(),
                            "TT Diff": row.xpath("./td[17]/text()").get(),
                            "W%": row.xpath("./td[18]/text()").get(),
                            "vW%": row.xpath("./td[19]/text()").get(),
                            "W% Diff": row.xpath("./td[20]/text()").get(),
                            "HR": row.xpath("./td[21]/text()").get(),
                            "HR/R": row.xpath("./td[22]/text()").get(),
                            "SB": row.xpath("./td[23]/text()").get(),
                            "H": row.xpath("./td[24]/text()").get(),
                            "SD 1-5": row.xpath("./td[25]/text()").get(),
                            "SD 1-9": row.xpath("./td[26]/text()").get(),
                        }
                        items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_advanced.__name__} [{self.spider}]")
        finally:
            return items
        

    def get_total(self):
        items = []
        try:
            resps = []
            response = self.driver.get_page(self.game_total_url, wait_selector="//table[@id='dataTable']")
            resps.append(response)
            other_btn = self.driver.exists("//button[not(contains(@class, 'button-clicked')) and contains(@id, 'searchdate')]")
            if other_btn:  # today
                self.driver.click("//button[not(contains(@class, 'button-clicked')) and contains(@id, 'searchdate')]", wait_after=5*1000)
                resps.append(self.driver.page.content())
            for resp in resps:
                sel = Selector(text=resp)
                for row in sel.xpath("//table[@id='dataTable']/tbody/tr"):
                    scraped_date = row.xpath("./td[3]/text()").get('')
                    if scraped_date in _date.replace("-",'/'):
                        item = {
                            "Date": row.xpath("./td[3]/text()").get(),
                            "Time": row.xpath("./td[4]/text()").get(),
                            "Game": row.xpath("./td[5]/text()").get(),
                            "Team": row.xpath("./td[6]/text()").get(),
                            "OL": row.xpath("./td[7]/text()").get(),
                            "Total (O/U)": row.xpath("./td[8]/text()").get(),
                            "O/U Over": row.xpath("./td[9]/text()").get(),
                            "O/U Under": row.xpath("./td[10]/text()").get(),
                            "Over W%": row.xpath("./td[11]/text()").get(),
                            "Under W%": row.xpath("./td[12]/text()").get(),
                            "Over EV": row.xpath("./td[13]/text()").get(),
                            "Under EV": row.xpath("./td[14]/text()").get(),
                            "Over Bet%": row.xpath("./td[15]/text()").get(),
                            "Under Bet%": row.xpath("./td[16]/text()").get(),
                            "Over Cash%": row.xpath("./td[17]/text()").get(),
                            "Under Cash%": row.xpath("./td[18]/text()").get(),
                        }
                        items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_total.__name__} [{self.spider}]")
        finally:
            return items

    
    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            ev_all = self.get_all()
            moneyline = self.get_moneyline()
            advanced = self.get_advanced()
            total = self.get_total()
            datas.append((ev_all, "EV all"))
            datas.append((moneyline, "EV ML"))
            datas.append((advanced, "EV Advanced"))
            datas.append((total, "EV Total"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)


###########################


class Dimers:
    url = "https://www.dimers.com/bet-hub/mlb/schedule"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__


    def get_dimers(self):
        items = []
        try:
            self.driver.get_page(self.url, wait_selector="//div[@class='external-match-list']")
            self.driver.click("//div[@class='dropdown-button']")
            self.driver.click(f"//button[@aria-label='{self.user_date}']")
            self.driver.page.mouse.wheel(1,1*1000)
            self.driver.page.wait_for_timeout(5*1000)
            response = self.driver.page.content()
            sel = Selector(response)
            for box in sel.xpath("//a[contains(@class,'game-link') and not(@draggable)]//div[@class='teams-col']"):
                for team in range(1,3):
                    item = {
                        "Team": box.xpath(f"./div[contains(@class, 'team-row')][{team}]/div[@class='team-name']/span/span/text()").get('').strip(),
                        "Percentage": box.xpath(f"./div[contains(@class, 'team-row')][{team}]/div[contains(@class,'team-prob')]/text()").get('').strip()
                    }
                    if item['Team']:
                        items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_dimers.__name__} [{self.spider}]")
        finally:
            return items
        

    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        date_local = datetime.datetime.strptime(_date, "%Y-%m-%d")
        self.user_date = "{} {}, {}".format(date_local.strftime("%B"), date_local.day, date_local.year)
        dimers = self.get_dimers()
        datas.append((dimers, "Dimers"))
        for data, sheet in datas:
            self.exporter.export(data, sheet)


###########################


class FanGraph:
    bullpen_url = "https://www.fangraphs.com/leaders/major-league?pos=all&stats=rel&lg=all&qual=0&season=2024&season1=2024&ind=0&team=0%2Cts&rost=0&filter=&players=0&type=8&month=3&pageitems=2000000000"
    batting_url = "https://www.fangraphs.com/leaders/major-league?pos=all&stats=bat&lg=all&qual=0&season=2024&season1=2024&ind=0&team=0%2Cts&rost=0&filter=&players=0&type=8&month=3&pageitems=2000000000"
    stuff_url = "https://www.fangraphs.com/leaders/major-league?pos=all&lg=all&season=2024&season1=2024&ind=0&team=0&stats=sta&qual=0&sortcol=12&sortdir=default&type=36&month=0&pagenum=1&pageitems=2000000000"
    pitchers_url = "https://www.fangraphs.com/leaders/major-league?pos=all&lg=all&season=2024&season1=2024&ind=0&team=0&stats=sta&type=8&month=3&qual=0&pageitems=2000000000"
    rp_url = "https://www.fangraphs.com/leaders/major-league?pos=all&lg=all&season=2024&season1=2024&ind=0&type=8&month=3&qual=0&stats=rel&team=0%2Cts&pageitems=2000000000"
    bat_url = "https://www.fangraphs.com/leaders/major-league?pos=all&lg=all&season=2024&season1=2024&ind=0&type=8&qual=0&stats=bat&team=0%2Cts&month=3&pageitems=2000000000"
    lhp_url = 'https://www.fangraphs.com/leaders/major-league?pos=all&stats=bat&lg=all&qual=y&season=2024&season1=2024&ind=0&team=0%2Cts&type=8&month=13&pageitems=2000000000'
    rhp_url = "https://www.fangraphs.com/leaders/major-league?pos=all&stats=bat&lg=all&qual=y&season=2024&season1=2024&ind=0&team=0%2Cts&type=8&month=14&pageitems=2000000000"
    records_url = "https://www.fangraphs.com/depthcharts.aspx?position=BaseRuns&pageitems=2000000000"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__


    def get_data(self, url):
        _items = []
        response = self.driver.get_page(url, wait_selector="//div[contains(@class, 'leaders-major_leaders-major')]//div[@class='table-scroll']/table", wait_after=10*1000)
        sel = Selector(response)
        if sel.xpath("//button[@aria-label='close']"):
            self.driver.click("//button[@aria-label='close']", wait_after=1*1000)
        response = self.driver.page.content()
        sel = Selector(response)
        table = sel.xpath("//div[contains(@class, 'leaders-major_leaders-major')]//div[@class='table-scroll']/table")
        for row in table.xpath("./tbody/tr"):
            item = {}
            for td in row.xpath("./td"):
                if td.xpath("./a/text()").get():
                    header = td.xpath('./@data-stat').get()
                    if header in item:
                        header += "_2"
                    item[header] = td.xpath("./a/text()").get('').strip()
                else:
                    header = td.xpath('./@data-stat').get()
                    if header in item:
                        header += "_2"
                    item[header] = td.xpath("./text()").get('').strip()
            _items.append(item)
        return _items


    def get_bullpen(self):
        items = []
        try:
            _items = self.get_data(self.bullpen_url)
            items.extend(_items)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_bullpen.__name__} [{self.spider}]")
        finally:
            return items
        
    
    def get_batting(self):
        items = []
        try:
            _items = self.get_data(self.batting_url)
            items.extend(_items)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_batting.__name__} [{self.spider}]")
        finally:
            return items


    def get_stuff(self):
        items = []
        try:
            _items = self.get_data(self.stuff_url)
            items.extend(_items)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_stuff.__name__} [{self.spider}]")
        finally:
            return items
    

    def get_pitchers(self):
        items = []
        try:
            _items = self.get_data(self.pitchers_url)
            items.extend(_items)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_pitchers.__name__} [{self.spider}]")
        finally:
            return items
        

    def get_rp(self):
        items = []
        try:
            _items = self.get_data(self.rp_url)
            items.extend(_items)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_rp.__name__} [{self.spider}]")
        finally:
            return items
    

    def get_bat(self):
        items = []
        try:
            _items = self.get_data(self.bat_url)
            items.extend(_items)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_bat.__name__} [{self.spider}]")
        finally:
            return items
    

    def get_lhp(self):
        items = []
        try:
            _items = self.get_data(self.lhp_url)
            items.extend(_items)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_lhp.__name__} [{self.spider}]")
        finally:
            return items
        
    
    def get_rhp(self):
        items = []
        try:
            _items = self.get_data(self.rhp_url)
            items.extend(_items)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_rhp.__name__} [{self.spider}]")
        finally:
            return items
        

    def get_records(self):
        items = []
        try:
            response = self.driver.get_page(self.records_url, wait_selector="//div[@id='content']//table")
            sel = Selector(response)
            tables = sel.xpath("//div[@id='content']//table")
            for table in tables:
                headers = [col.xpath("./div/text()").get() for col in table.xpath("./thead/tr[2]/th")]
                for row in table.xpath("./tbody/tr"):
                    item = {}
                    for header, td in zip(headers, row.xpath("./td")):
                        if td.xpath("./a/text()").get():
                            if header in item:
                                header += "_2"
                            item[header] = td.xpath("./a/text()").get('').strip()
                        else:
                            if header in item:
                                header += "_2"
                            item[header] = td.xpath("./text()").get('').strip()
                    items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_records.__name__} [{self.spider}]")
        finally:
            return items
        

    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        bullpen = self.get_bullpen()
        batting = self.get_batting()
        stuff = self.get_stuff()
        pitchers = self.get_pitchers()
        rp = self.get_rp()
        bat = self.get_bat()
        lhp = self.get_lhp()
        rhp = self.get_rhp()
        records = self.get_records()
        datas.append((bullpen, "Bullpen"))
        datas.append((batting, "Batting"))
        datas.append((stuff, "Stuff"))
        datas.append((pitchers, "Pitcher30"))
        datas.append((rp, "RP30"))
        datas.append((bat, "Bat30"))
        datas.append((lhp, "TeamVLHP"))
        datas.append((rhp, "TeamVRHP"))
        datas.append((records, "Records"))
        for data, sheet in datas:
            self.exporter.export(data, sheet)

        
###########################


class Dime:
    odds_url = "https://www.sportsbettingdime.com/mlb/odds/"
    trends_url = "https://www.sportsbettingdime.com/mlb/public-betting-trends/"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__


    def login(self):
        try:
            response = self.driver.get_page("https://www.sportsbettingdime.com/plus/register/", wait_after=5*1000)
            if is_exist(response, "//a[text()='PLUS']"):
                raise TimeoutError("Already logged in")
            self.driver.page.locator("(//div[@class='d-flex flex-column align-items-center']/div[1]//input)[1]").fill("diego.lomanto@gmail.com")
            self.driver.page.locator("(//div[@class='d-flex flex-column align-items-center']/div[1]//input)[2]").fill("v5gFU51^*0PO")
            self.driver.page.wait_for_timeout(1000)
            self.driver.click("//div[@class='d-flex flex-column align-items-center']/div[1]//button")
            self.driver.wait_for_selector("//a[text()='PLUS']")
            logger.debug("logged in")
            return True
        except TimeoutError:
            return True
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.login.__name__} [{self.spider}]")
            return False
    

    def get_odds(self):
        items = []
        try:
            self.driver.get_page("https://www.sportsbettingdime.com/mlb/odds/")
            self.driver.page.get_by_label("moneyline").click()
            self.driver.page.get_by_role("option", name="total").click()
            self.driver.page.wait_for_timeout(15*1000)
            response = self.driver.page.content()
            sel = Selector(text=response)
            for _match in sel.xpath("//tr[@class='MuiTableRow-root']"):
                date_str = _match.xpath("./th/div[contains(@class, 'rowShowDate')]/text()").get()
                match_date = dateparser.parse(date_str).date().strftime("%Y-%m-%d") if date_str else None
                if match_date == _date:
                    for team, name in zip(_match.xpath(".//div[contains(@data-id, '-best') and not(@role)]"), _match.xpath(".//div[contains(@class, 'nameTeam')]/text()").getall()):
                        total = team.xpath("./following-sibling::div[contains(@class, 'oddsText')]/div[contains(@class, 'first')]/text()").re_first("[0-9.]+")
                        over_under = team.xpath("./following-sibling::div[contains(@class, 'oddsText')]/div[contains(@class, 'first')]/text()").re_first("[a-z]")
                        best_odds = team.xpath("./following-sibling::div[contains(@class, 'oddsText')]/div[contains(@class, 'second')]/text()").re_first("[0-9+-]+")
                        book_icon = team.xpath("./following-sibling::div[contains(@class, 'bookLogoOuter')]/img/@src").get('').split('/')[-1]
                        items.append({
                            "Team": name,
                            "Over/Under": over_under,
                            "Total": total,
                            "Best Odds": best_odds,
                            "Book Icon": book_icon
                        })
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_odds.__name__} [{self.spider}]")
        finally:
            return items
    

    def get_trends(self):
        items = []
        try:
            self.driver.get_page("https://www.sportsbettingdime.com/mlb/public-betting-trends/")
            self.driver.click("//div[@id='week']")
            self.driver.page.locator(f"//li[@data-value='{_date}']").click()
            self.driver.page.wait_for_timeout(10*1000)
            response = self.driver.page.content()
            sel = Selector(text=response)
            for table in sel.xpath("//table[contains(@class, 'odds')]"):
                stat_link = table.xpath(".//a[contains(@href, 'sportsbettingdime')]/@href").get()
                stat_response = self.driver.get_page(stat_link)
                if stat_response:
                    stat_sel = Selector(text=stat_response)
                    teams = []
                    for indx, row in enumerate(table.xpath("./tbody/tr"), start=1):
                        team = row.xpath("./td[1]/div[1]/div[2]/text()").get()
                        spread_money = row.xpath("./td[6]/div//text()").get()
                        spread_bet = row.xpath("./td[7]/div//text()").get()
                        moneyline_money = row.xpath("./td[9]/div//text()").get()
                        moneyline_bet = row.xpath("./td[10]/div//text()").get()
                        total_money = row.xpath("./td[12]/div//text()").get()
                        total_bet = row.xpath("./td[13]/div//text()").get()
                        if indx == 1:
                            predicted_score = stat_sel.xpath("//div[@class='row']//p[@class='AccuracyComparison_percents__24WHS']//ancestor::div[@class='row']/div[1]//p[@class='AccuracyComparison_percents__24WHS']/text()[1]").get()
                            win_probability = stat_sel.xpath("//div[@class='row']//p[@class='AccuracyComparison_percents__24WHS']//ancestor::div[@class='row']/div[2]//p[@class='AccuracyComparison_percents__24WHS']/text()[1]").get()
                        else:
                            predicted_score = stat_sel.xpath("//div[@class='row']//p[@class='AccuracyComparison_percents__24WHS']//ancestor::div[@class='row']/div[1]//p[@class='AccuracyComparison_percents__24WHS']/text()[3]").get()
                            win_probability = stat_sel.xpath("//div[@class='row']//p[@class='AccuracyComparison_percents__24WHS']//ancestor::div[@class='row']/div[2]//p[@class='AccuracyComparison_percents__24WHS']/text()[3]").get()
                        teams.append({
                            "Team": team,
                            "Spread Money": spread_money,
                            "Spread Bet": spread_bet,
                            "Moneyline Money": moneyline_money,
                            "Moneyline Bet": moneyline_bet,
                            "Total Money": total_money,
                            "Total Bet": total_bet,
                            "Predicted Score": predicted_score,
                            "Win Probability": win_probability
                        })
                    total_predicted_score = sum([float(team.get("Predicted Score", 0)) for team in teams if team and team.get("Predicted Score")])
                    for team in teams:
                        team['Total'] = total_predicted_score if total_predicted_score else 'TBD'
                        items.append(team)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_trends.__name__} [{self.spider}]")
        finally:
            return items
        

    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            odds = self.get_odds()
            trends = self.get_trends()
            datas.append((odds, "SPD Total"))
            datas.append((trends, "Sporting Dime"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)


###########################


class BetQl:
    
    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__


    def login(self):
        try:
            response = self.driver.get_page("https://betql.co/mlb/odds", wait_after=5*1000)
            if is_exist(response, "//div[@class='user-pic']"):
                raise TimeoutError("Already logged in")
            self.driver.page.get_by_role("button", name="Log In").click()
            self.driver.page.wait_for_timeout(1000)
            self.driver.page.get_by_placeholder("Enter e-mail address").fill("diego.lomanto@gmail.com")
            self.driver.page.get_by_placeholder("Enter password").fill("7!W?\\05o`v92")
            self.driver.page.wait_for_timeout(1000)
            self.driver.click("//form[@class='rotoql-login__form']//button[text()='Log In']")
            self.driver.wait_for_selector("//form[@class='rotoql-login__form']//button[text()='Log In']", state="hidden")
            logger.debug("logged in")
            return True
        except TimeoutError:
            return True
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.login.__name__} [{self.spider}]")
            return False
    

    def get_odds(self):
        items = []
        try:
            day = datetime.datetime.strptime(_date, "%Y-%m-%d").day
            self.driver.wait_for_selector("//div[@class='games-container']")
            self.driver.click("//div[@class='d-none d-sm-flex games-view__filter-container']//button[contains(@class, 'rotoql-date-picker__button')]", wait_after=1*1000)
            self.driver.click(f"//div[@class='rotoql-date-picker__menu dropdown-menu show']//div[contains(@class,'rotoql-date-picker__calendar-cell ') and not(contains(@class, 'disabled'))]/span[text()='{day}']", wait_after=1*1000)
            self.driver.wait_for_selector("//a[@class='games-table-column__team-link'][last()]")
            sel = Selector(self.driver.page.content())
            for link in sel.xpath("//div[@class='games-table-column']/div/a"):
                url = urljoin("https://betql.co", link.xpath("./@href").get())
                self.driver.get_page(url)
                self.driver.page.mouse.wheel(1,1000)
                self.driver.wait_for_selector("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]")
                response = self.driver.page.content()

                self.driver.click("//div[@id='total']")
                total_sel = Selector(self.driver.page.content())
                total_model_bets = total_sel.xpath("//div[@class='rating-trend__favorite']/text()").get()
                total_rating = total_sel.xpath("//div[@class='rating-trend__title']/text()").get()
                game_total = total_sel.xpath("//span[contains(text(), ' runs')]/span/text()").get('')

                sel = Selector(response)
                team1 = sel.xpath("//div[@class='team-header right']//div[@class='team-full-name']/text()").get()
                team2 = sel.xpath("//div[@class='team-header left']//div[@class='team-full-name']/text()").get()
                moneyline_model_bets = sel.xpath("//div[@class='rating-trend__favorite']/text()").get()
                moneyline_rating = sel.xpath("//div[@class='rating-trend__title']/text()").get()

                for i in range(1, 3):
                    if i == 1:
                        team = team1
                        proj_full_score = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[1]/span[1]/span/text()").get()
                        proj_win = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[2]/span[1]/span/text()").get()
                        first_half_score = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[3]/span[1]/span/text()").get()
                        first_half_win = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[4]/span[1]/span/text()").get()
                        team_grade = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[6]/span[1]/span/text()").get()
                        starting_pitcher_grade = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[7]/span[1]/span/text()").get()
                        offense_grade = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[8]/span[1]/span/text()").get()
                        pitching_grade = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[9]/span[1]/span/text()").get()
                        
                        moneyline_percent_of_money = sel.xpath("(//div[@class='sharp-report__drawer-text '])[1]/text()").re_first("\d+%")
                        moneyline_percent_of_ticket = sel.xpath("(//div[@class='sharp-report__drawer-text '])[2]/text()").re_first("\d+%")
                        total_percent_of_money = total_sel.xpath("(//div[@class='sharp-report__drawer-text '])[1]/text()").re_first("\d+%")
                        total_percent_of_ticket = total_sel.xpath("(//div[@class='sharp-report__drawer-text '])[2]/text()").re_first("\d+%")


                    elif i == 2:
                        team = team2
                        proj_full_score = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[1]/span[3]/span/text()").get()
                        proj_win = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[2]/span[3]/span/text()").get()
                        first_half_score = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[3]/span[3]/span/text()").get()
                        first_half_win = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[4]/span[3]/span/text()").get()
                        team_grade = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[6]/span[3]/span/text()").get()
                        starting_pitcher_grade = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[7]/span[3]/span/text()").get()
                        offense_grade = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[8]/span[3]/span/text()").get()
                        pitching_grade = sel.xpath("//div[@class='best-bets__main']/div[3]/div/div[contains(@class, 'projections-list')]/div[9]/span[3]/span/text()").get()
                        
                        moneyline_percent_of_money = sel.xpath("(//div[@class='sharp-report__drawer-text '])[3]/text()").re_first("\d+%")
                        moneyline_percent_of_ticket = sel.xpath("(//div[@class='sharp-report__drawer-text '])[4]/text()").re_first("\d+%")
                        total_percent_of_money = total_sel.xpath("(//div[@class='sharp-report__drawer-text '])[3]/text()").re_first("\d+%")
                        total_percent_of_ticket = total_sel.xpath("(//div[@class='sharp-report__drawer-text '])[4]/text()").re_first("\d+%")
                    item = {
                        "Team": team,
                        "Proj Full Score": proj_full_score,
                        "Proj Win %": proj_win,
                        "First Half Score": first_half_score,
                        "First Half Win %": first_half_win,
                        "Team Grade": team_grade,
                        "Starting Pitcher Grade": starting_pitcher_grade,
                        "Offense Grade": offense_grade,
                        "Pitching Grade": pitching_grade,
                        "Moneyline Model Bets": moneyline_model_bets,
                        "Moneyline Rating": moneyline_rating.split('Rating')[0].strip() if moneyline_rating else moneyline_rating,
                        "Moneyline % of Money": moneyline_percent_of_money,
                        "Moneyline % of Tickets": moneyline_percent_of_ticket,
                        "Game Total": game_total,
                        "Total Model Bets": total_model_bets,
                        "Total Rating": total_rating.split('Rating')[0].strip() if total_rating else total_rating,
                        "Over Total % of Money": total_percent_of_money,
                        "Over Total % of Tickets": total_percent_of_ticket,
                        "Under Total % of Money": total_percent_of_money,
                        "Under Total % of Tickets": total_percent_of_ticket,
                    }
                    if item['Moneyline Rating'] == 'Star':
                        item['Moneyline Rating'] = ''	
                    if item['Total Rating'] == 'Star':
                        item['Total Rating'] = ''
                    if 'matchup' in item['Game Total']:
                        item['Game Total'] = ''				
                    items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_odds.__name__} [{self.spider}]")
        finally:
            return items
        
    
    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            odds = self.get_odds()
            datas.append((odds, "BetQL"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)
    

###########################


class SportsLine:
    expert_url = "https://www.sportsline.com/mlb/picks/experts/"
    moneyline_url = 'https://www.sportsline.com/mlb/picks/?pickType=MONEY_LINE'
    spread_url = "https://www.sportsline.com/mlb/picks/experts/?pickType=POINT_SPREAD"
    ou_url = 'https://www.sportsline.com/mlb/picks/experts/?pickType=OVER_UNDER'


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__

    
    def login(self):
        try:
            response = self.driver.get_page("https://www.sportsline.com/login/")
            if is_exist(response, "//a[contains(@da-tracking-nav, 'user-name-my-account')]"):
                raise TimeoutError("Already logged in")
            self.driver.page.locator("//input[@id='loginId']").fill("diego.lomanto@gmail.com")
            self.driver.page.locator("//input[@id='password']").fill("6rw6SgQMM#HZ4t$")
            self.driver.click("//button[text()='Log In']")
            self.driver.wait_for_selector("//button[text()='Log In']", state="hidden")
            logger.debug("logged in")
            return True
        except TimeoutError:
            return True
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.login.__name__} [{self.spider}]")
            return False


    @staticmethod
    def extract_percentage(s):
        match = re.search(r'(\d+(\.\d+)?)%', s)
        if match:
            first = float(match.group(1))
            second = 100 - first
            return f"{first}%", f"{second}%"


    def parse(self, response):
        _items = []
        sel = Selector(response)
        that_day = (datetime.datetime.strptime(_date, "%Y-%m-%d") - datetime.timedelta(days=1)).strftime('%m/%d')
        this_day = datetime.datetime.strptime(_date, "%Y-%m-%d").strftime('%m/%d')
        for expert in sel.xpath("//main[@display]//section[@data-id]"):
            scraped_date = expert.xpath(".//span[contains(text(), '2024')]/text()").get('').split(",")[0]
            parsed_date = datetime.datetime.strptime(scraped_date, "%b %d %Y").strftime('%m/%d') if scraped_date else ''
            if f"{that_day}" in parsed_date:
                break
            team = expert.xpath(".//a[contains(@data-tracking-value,'market-type-moneyline') or contains(@data-tracking-value,'market-type-spread') or contains(@data-tracking-value,'market-type-total')]//span[contains(text(), 'Money') or contains(text(), 'Spread') or contains(text(), 'Over')]/following-sibling::span/text()").re_first("[a-zA-z\s\.]+")
            pick = expert.xpath(".//a[contains(@data-tracking-value,'market-type-moneyline') or contains(@data-tracking-value,'market-type-spread') or contains(@data-tracking-value,'market-type-total')]//span[contains(text(), 'Money') or contains(text(), 'Spread') or contains(text(), 'Over')]/following-sibling::span/text()").re_first("[-\+\d]+")
            analysis = "".join(expert.xpath(".//span[contains(text(), 'Analysis')]/following-sibling::p/text()").getall()).replace("ANALYSIS:",'').strip()
            expert_name = expert.xpath(".//a[@data-tracking-value='expert-picks_click_profile-avatar']//span[@color]/text()").get('')
            if f"{this_day}" in parsed_date and pick:
                if 'under' in team.lower() or 'over' in team.lower():
                    pick = team + pick
                    if 'under' in team.lower():
                        team = expert.xpath(".//div[@direction='column']//div/span[text() and @color and @font-weight]/text()").getall()[1]
                    elif 'over' in team.lower():
                        team = expert.xpath(".//div[@direction='column']//div/span[text() and @color and @font-weight]/text()").getall()[0]
                _items.append({
                    "Team": team,
                    "Pick": pick,
                    "Analysis": analysis,
                    "Expert": expert_name
                })
        return _items
    

    def get_target(self, url):
        items = []
        try:
            self.driver.get_page(url)
            for _ in range(5): # scroll down x times
                self.driver.page.locator("//span[contains(text(), 'Load')]").scroll_into_view_if_needed()
                self.driver.click("//span[contains(text(), 'Load')]/parent::button", wait_after=1*1000)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_target.__name__} [{self.spider}]")
        finally:
            _items = self.parse(self.driver.page.content())
            if _items:
                items.extend(_items)
            return items
        
    
    def get_moneyline(self):
        items = []
        try:
            response = self.driver.get_page(self.moneyline_url)
            sel = Selector(response)
            for match, date_str in zip(sel.xpath("//td[@data-testid='CompetitionRow-gameForcast']/a/@href").getall(), sel.xpath("//tr[@class='game-date-line']//small/text()").getall()):
                match_date = dateparser.parse(date_str).date().strftime("%Y-%m-%d") if dateparser.parse(date_str) else 'future'
                if match_date == _date:
                    url = urljoin(self.driver.page.url, match)
                    response = self.driver.get_page(url)

                    sel = Selector(response)
                    percent_team_name = sel.xpath("//p[contains(text(), 'simulation average moneyline')]/parent::div/div[2]//span[not(@grade)]/text()").get()
                    first_percent, second_percent = self.extract_percentage(sel.xpath("//p[contains(text(), 'simulation average moneyline')]/text()").get())
                    for i in [1,3]:
                        team = " ".join(sel.xpath(f"(//div[@spacing='none' and @direction='horizontal'])/preceding-sibling::div[2]/div[4]/div[{i}]/div[2]//text()").getall()[:-1])
                        projected_score = sel.xpath(f"(//div[@spacing='none' and @direction='horizontal'])/preceding-sibling::div[2]/div[4]/div[2]/div/div/div[{i}]/text()").get() 
                        item = {
                            "Team": team,
                            "Projected Score": projected_score,
                            "Simulation Picks Moneyline": first_percent if percent_team_name.lower() in team.lower() else second_percent
                        }
                        items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_moneyline.__name__} [{self.spider}]")
        finally:
            return items
        
    
    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            expert = self.get_target(self.expert_url)
            moneyline = self.get_moneyline()
            spread = self.get_target(self.spread_url)
            ou = self.get_target(self.ou_url)
            if spread:
                expert.extend(spread)
            datas.append((expert, "SP Expert"))
            datas.append((moneyline, "Sportsline"))
            datas.append((ou, "SP OU"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)


###########################


class PayDirt:
    paydirt_url = "https://paydirtdfs.com/mlb-paywalled/mlb-game-betting-model/"


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
            self.driver.click("//input[@id='wp-submit']")
            self.driver.wait_for_selector("//input[@id='wp-submit']", state="hidden")
            logger.debug("logged in")
            return True
        except TimeoutError as e:
            return True
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.login.__name__} [{self.spider}]")
            return False
    

    def get_paydirt(self):
        items = []
        try:
            self.driver.get_page(self.paydirt_url, wait_selector="//iframe")
            iframe = self.driver.page.frames[1]
            self.driver.wait_for_selector(iframe=iframe, selector="//p[contains(text(), 'Export')]/ancestor::button")
            with self.driver.page.expect_download() as download_file:
                self.driver.click(iframe=iframe, selector="//p[contains(text(), 'Export Team Model')]/ancestor::button", wait_after=2*1000)
            response = requests.get(url=download_file.value.url)
            with open("paydirt.csv", "wb") as f:
                f.write(response.content)
            df = pd.read_csv("paydirt.csv")
            os.remove("paydirt.csv")
            items.extend(df.to_dict(orient="records"))
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_paydirt.__name__} [{self.spider}]")
        finally:
            return items
        

    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        if self.login():
            paydirt = self.get_paydirt()
            datas.append((paydirt, "Paydirt"))
            for data, sheet in datas:
                self.exporter.export(data, sheet)


###########################


class Rotoballer:
    url = "https://www.rotoballer.com/starting-pitcher-dfs-matchups-streamers-tool?date={}"


    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__

    
    def get_pitchers(self):
        items = [] 
        try:
            self.driver.get_page(self.url.format(datetime.datetime.today().strftime("%Y-%m-%d").replace('-','')), wait_selector="//div[@id='player_stats']")
            self.driver.page.select_option("//select", value=f"?date={_date.replace('-','')}")
            self.driver.page.wait_for_timeout(5*1000)
            self.driver.wait_for_selector("//div[@id='player_stats']")
            response = self.driver.page.content()
            sel = Selector(response)
            headers = []
            for header in sel.xpath("//table/thead/tr[2]/th"):
                headers.append(" ".join(header.xpath(".//text()").getall()).strip())
            for row in sel.xpath("//table/tbody/tr"):
                cells = row.xpath("./td//text()").getall()
                item = {}
                for header, value in zip(headers, cells):
                    if header in item:
                        header += "_2"
                    item[header] = value
                items.append(item)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_pitchers.__name__} [{self.spider}]")
        finally:
            return items
        

    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        pitchers = self.get_pitchers()
        datas.append((pitchers, "Pitchers"))
        for data, sheet in datas:
            self.exporter.export(data, sheet)


###########################


class Gsheet:

    def __init__(self, driver: WebDriver, exporter: FeedExporter) -> None:
        self.driver = driver
        self.exporter = exporter
        self.spider = self.__class__.__name__


    @staticmethod
    def get_date():
        date_object = datetime.datetime.strptime(_date, "%Y-%m-%d")
        try:
            formatted_date = date_object.strftime("%-m/%-d/%y") # For Linux
        except ValueError:
            formatted_date = date_object.strftime("%#m/%#d/%y")  # For Windows
        return formatted_date
    

    def get_sheet_content(self, sheet_url):
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet(self.get_date())
        list_of_lists = worksheet.get_all_values()
        data = [list_of_lists[0]]
        for l in list_of_lists[1:]:
            if l[0].isdigit():
                data.append(l)
        return data
    

    def get_sheet(self):
        items = []
        try:
            self.driver.get_page("https://docs.google.com/spreadsheets/d/1p2V2AmeF2mZIjQU0zza_A2OcYHcfZblJi6fefdFVhbA/edit#gid=2132695405", wait_after=2*1000)
            self.driver.click(f"//span[@class='docs-sheet-tab-name' and text() = '{self.get_date()}']//ancestor::div[@role='button']", wait_after=5*1000)
            url = self.driver.page.url

            items = []
            data = self.get_sheet_content(url)
            headers = data[0][:7] 
            previous_left_total_runs = ''
            previous_right_total_runs = ''
            for row in data[1:]:
                left_side, right_side = row[:8], row[8:]
                left_dict = {headers[i]: left_side[i] for i in range(len(headers))}

                left_total_runs = left_dict.get("Total Runs")
                if left_total_runs:
                    previous_left_total_runs = left_total_runs
                else:
                    left_dict['Total Runs'] = previous_left_total_runs 

                right_dict = {headers[i]: right_side[i] for i in range(len(headers))}
                right_total_runs = right_dict.get("Total Runs")
                if right_total_runs:
                    previous_right_total_runs = right_total_runs
                else:
                    right_dict['Total Runs'] = previous_right_total_runs
                items.append(left_dict)
                items.append(right_dict)
        except Exception as e:
            logger.error(e)
            logger.debug(f"Error while {self.get_sheet.__name__} [{self.spider}]")
        finally:
            return items


    def crawl(self):
        datas = []
        logger.info(f"Crawling {self.spider}")
        sheet = self.get_sheet()
        datas.append((sheet, "GP"))
        for data, sheet in datas:
            self.exporter.export(data, sheet)


###########################


driver = WebDriver(timeout=60*1000, headless=True) # headless=False to show the browser
exporter = FeedExporter(filename="mlb_daily_slate.xlsx")

spiders = [
    BallParker(driver, exporter),
    ActionNetwork(driver, exporter),
    EvAnalytics(driver, exporter),
    Dimers(driver, exporter),
    FanGraph(driver, exporter),
    Dime(driver, exporter),
    BetQl(driver, exporter),
    SportsLine(driver, exporter),
    PayDirt(driver, exporter),
    Rotoballer(driver, exporter),
    Gsheet(driver, exporter)
]

try:
    for spider in spiders:
        spider.crawl()
except (Exception, KeyboardInterrupt):
    pass
driver.close()
exporter.close()