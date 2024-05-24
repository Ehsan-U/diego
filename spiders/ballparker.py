import os
import pandas as pd
from parsel import Selector
from common import logger, WebDriver, FeedExporter

_date = input("Date: ") # 2024-05-24


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


driver = WebDriver(headless=True)
exporter = FeedExporter("workbook.xlsx")
p = BallParker(driver, exporter)
p.crawl()
driver.close()
exporter.close()