from browser_manager import ChromeBrowserManager
from config import AppConfig
from overleaf_automation import OverleafProjectSharer


def main() -> None:
    config = AppConfig.from_environment()
    browser_manager = ChromeBrowserManager(
        user_data_dir=config.user_data_dir,
        start_maximized=config.start_maximized,
    )

    driver = None
    try:
        driver = browser_manager.create_driver()
        automation = OverleafProjectSharer(driver, config)
        automation.run()
    except Exception as error:
        print(f"❌ ERROR: {error}")
    finally:
        browser_manager.quit_driver(driver)


if __name__ == "__main__":
    main()

