from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


class ChromeBrowserManager:
    def __init__(self, user_data_dir: Path, start_maximized: bool = True) -> None:
        self.user_data_dir = Path(user_data_dir)
        self.start_maximized = start_maximized

    def create_driver(self) -> webdriver.Chrome:
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        options = Options()
        if self.start_maximized:
            options.add_argument("--start-maximized")
        options.add_argument(f"--user-data-dir={self.user_data_dir}")
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)

    @staticmethod
    def quit_driver(driver: webdriver.Chrome | None) -> None:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                # Driver/session may already be terminated by browser crash or manual close.
                pass