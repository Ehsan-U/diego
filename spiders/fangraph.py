from common import WebDriver, FeedExporter, logger
from parsel import Selector


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



driver = WebDriver(timeout=60000)
exporter = FeedExporter(filename="workbook.xlsx")
fangraph = FanGraph(driver, exporter)
fangraph.crawl()
driver.close()
exporter.close()