from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from typing import List, Optional
import json
import logging

from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FileScrapeNYPUCInfo(BaseModel):
    serial: str
    date_filed: str
    nypuc_doctype: str
    name: str
    url: str
    organization: str
    itemNo: str
    file_name: str
    docket_id: str


class NYPUCFilingObject(BaseModel):
    case: str
    filings: List[FileScrapeNYPUCInfo]


class NYPUCDocketInfo(BaseModel):
    docket_id: str  # 24-C-0663
    matter_type: str  # Complaint
    matter_subtype: str  # Appeal of an Informal Hearing Decision
    industry_affected: str
    title: str  # In the Matter of the Rules and Regulations of the Public Service
    organization: str  # Individual
    date_filed: str  # 12/13/2022


class DocketProcessor:
    def __init__(
        self, driver: WebDriver, base_url: str = "https://example.gov/CaseMaster.aspx"
    ):
        self.driver = driver
        self.base_url = base_url

    def process_docket(self, docket_info: NYPUCDocketInfo) -> Optional[NYPUCFilingObject]:
        """Main method to process a docket and return filings"""
        try:
            url = self._construct_url(docket_info.docket_id)
            if not self._navigate_to_docket(url):
                return None

            return self._extract_and_process_filings(docket_info.docket_id)
        except Exception as e:
            self._handle_error(docket_info.docket_id, e)
            return None

    def _construct_url(self, docket_id: str) -> str:
        """Construct the URL for a docket page"""
        return f"{self.base_url}?MatterCaseNo={docket_id}"

    def _navigate_to_docket(self, url: str, timeout: int = 30) -> bool:
        """Navigate to docket URL and wait for page load"""
        try:
            self.driver.get(url)
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.ID, "tblPubDoc"))
            )
            return True
        except TimeoutException:
            logger.error(f"Timeout waiting for docket page to load: {url}")
            return False

    def _extract_and_process_filings(self, docket_id: str) -> NYPUCFilingObject:
        """Extract filings from the page and process them"""
        try:
            filing_object = self._extract_filings(docket_id)
            self._save_filings(filing_object)
            return filing_object
        except NoSuchElementException as e:
            logger.error(f"Missing expected page elements for docket {docket_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error processing filings for docket {docket_id}: {e}")
            raise

    def _extract_filings(self, docket_id: str) -> NYPUCFilingObject:
        """Extract filings data from the page table"""
        filings = []
        table = self.driver.find_element(By.ID, "tblPubDoc")

        for row in table.find_elements(By.CSS_SELECTOR, "tbody tr"):
            try:
                filings.append(self._parse_row(row, docket_id))
            except Exception as e:
                logger.warning(f"Skipping invalid row in docket {docket_id}: {e}")

        return NYPUCFilingObject(case=docket_id, filings=filings)

    def _parse_row(self, row, docket_id: str) -> FileScrapeNYPUCInfo:
        """Parse a single table row into FileScrapeNYPUCInfo"""
        cells = row.find_elements(By.TAG_NAME, "td")
        link = cells[3].find_element(By.TAG_NAME, "a")

        return FileScrapeNYPUCInfo(
            serial=cells[0].text.strip(),
            date_filed=cells[1].text.strip(),
            nypuc_doctype=cells[2].text.strip(),
            name=link.text.strip(),
            url=link.get_attribute("href").strip(),
            organization=cells[4].text.strip(),
            itemNo=cells[5].text.strip(),
            file_name=cells[6].text.strip(),
            docket_id=docket_id,
        )

    def _save_filings(self, filing_object: NYPUCFilingObject):
        """Save processed filings to JSON file"""
        filename = f"filings_{filing_object.case}.json"
        with open(filename, "w") as f:
            json.dump(filing_object.dict(), f, indent=2)
        logger.info(f"Saved {len(filing_object.filings)} filings to {filename}")

    def _handle_error(self, docket_id: str, error: Exception):
        """Handle errors and log them"""
        error_info = {
            "docket_id": docket_id,
            "error_type": type(error).__name__,
            "message": str(error),
        }

        logger.error(f"Error processing docket {docket_id}: {error}")

        # Save error details
        try:
            with open("error_log.json", "a") as f:
                json.dump(error_info, f)
                f.write("\n")
        except Exception as e:
            logger.error(f"Failed to save error log: {e}")


# Usage Example
if __name__ == "__main__":
    driver = webdriver.Chrome()
    processor = DocketProcessor(driver)

    sample_docket = NYPUCDocketInfo(
        docket_id="24-C-0663",
        matter_type="Complaint",
        matter_subtype="Appeal of an Informal Hearing Decision",
        industry_affected="Utilities",
        title="In the Matter of the Rules and Regulations of the Public Service",
        organization="Individual",
        date_filed="12/13/2022",
    )

    result = processor.process_docket(sample_docket)

    if result:
        print(f"Processed {len(result.filings)} filings for docket {result.case}")
    else:
        print("Failed to process docket")

    driver.quit()
