from parsel import Selector
from common import logger, WebDriver, is_exist, FeedExporter



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



driver = WebDriver(headless=True)
exporter = FeedExporter("workbook.xlsx")
p = PropsCash(driver, exporter)
p.crawl()
driver.close()
exporter.close()