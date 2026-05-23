from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from browser_manager import ChromeBrowserManager
from config import AppConfig
from overleaf_automation import ManualLoginRequired, OverleafProjectSharer


def run_overleaf_automation(config: AppConfig) -> None:
    browser_manager = ChromeBrowserManager(
        user_data_dir=config.user_data_dir,
        start_maximized=config.start_maximized,
    )

    driver = None
    try:
        driver = browser_manager.create_driver(headless=True)
        automation = OverleafProjectSharer(driver, config, interactive_login=False)
        recipients = automation.load_recipients()

        try:
            automation.ensure_logged_in()
        except ManualLoginRequired:
            automation, driver = _perform_visible_login_then_resume_headless(
                browser_manager,
                config,
                driver,
                login_kind="overleaf",
            )

        for recipient in recipients:
            project_name = automation.build_project_name(recipient)
            share_link = ""

            while not share_link:
                try:
                    automation.open_project_or_template()
                    automation.rename_project(project_name)
                    automation.open_share_dialog()
                    share_link = automation.set_link_sharing_to_edit_and_copy_link()
                    automation.save_link_to_csv(share_link, project_name)
                except ManualLoginRequired:
                    automation, driver = _perform_visible_login_then_resume_headless(
                        browser_manager,
                        config,
                        driver,
                        login_kind="overleaf",
                    )

            while True:
                try:
                    automation.send_email_via_gmail(
                        recipient=recipient,
                        share_link=share_link,
                        project_name=project_name,
                    )
                    break
                except ManualLoginRequired:
                    automation, driver = _perform_visible_login_then_resume_headless(
                        browser_manager,
                        config,
                        driver,
                        login_kind="gmail",
                    )
    finally:
        browser_manager.quit_driver(driver)


def build_config_with_csv(config: AppConfig, csv_path: str | Path) -> AppConfig:
    return replace(config, recipients_csv_path=Path(csv_path))


def _switch_to_visible_driver(
    browser_manager: ChromeBrowserManager,
    config: AppConfig,
    current_driver,
) -> tuple[OverleafProjectSharer, object]:
    print("🔄 Login required. Relaunching Chrome visibly for manual sign-in...")
    browser_manager.quit_driver(current_driver)
    driver = browser_manager.create_driver(headless=False)
    automation = OverleafProjectSharer(driver, config, interactive_login=True)
    return automation, driver


def _perform_visible_login_then_resume_headless(
    browser_manager: ChromeBrowserManager,
    config: AppConfig,
    current_driver,
    login_kind: str,
) -> tuple[OverleafProjectSharer, object]:
    automation, visible_driver = _switch_to_visible_driver(browser_manager, config, current_driver)

    if login_kind == "gmail":
        automation.ensure_gmail_logged_in()
    else:
        automation.ensure_logged_in()

    browser_manager.quit_driver(visible_driver)
    headless_driver = browser_manager.create_driver(headless=True)
    headless_automation = OverleafProjectSharer(headless_driver, config, interactive_login=False)
    if login_kind == "gmail":
        headless_automation.ensure_gmail_logged_in()
    else:
        headless_automation.ensure_logged_in()
    return headless_automation, headless_driver