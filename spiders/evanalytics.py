from common import *



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
            self.driver.click("//button[@data-val='TB' and @class='group-button']", wait_after=5*1000)
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


driver = WebDriver(headless=True)
exporter = FeedExporter("workbook.xlsx")
p = EvAnalystics(driver, exporter)
p.crawl()
driver.close()
exporter.close()