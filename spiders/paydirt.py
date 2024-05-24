import os
import pandas as pd
from common import logger, WebDriver, is_exist, FeedExporter



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
            iframe.wait_for_timeout(5000)
            download_file.value.save_as("paydirt.csv")
            df = pd.read_csv("paydirt.csv")
            os.remove("paydirt.csv")
            return df.to_dict(orient="records", index=False)
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


driver = WebDriver(timeout=60*1000, headless=True)
exporter = FeedExporter("workbook.xlsx")
p = Paydirt(driver, exporter)
p.crawl()
driver.close()
exporter.close()