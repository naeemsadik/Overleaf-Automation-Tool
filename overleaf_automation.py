import time
import csv
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import AppConfig


@dataclass(frozen=True)
class TeamRecipient:
    team_id: str
    project_title: str
    team_leader_name: str
    team_leader_email: str


class SeleniumWorkflowBase:
    def __init__(self, driver, config: AppConfig) -> None:
        self.driver = driver
        self.config = config
        self.wait = WebDriverWait(driver, config.wait_timeout)

    def open_page(self, url: str) -> None:
        self.driver.get(url)

    def wait_for_clickable(self, by: By, selector: str):
        return self.wait.until(EC.element_to_be_clickable((by, selector)))

    def wait_for_visible(self, by: By, selector: str):
        return self.wait.until(EC.visibility_of_element_located((by, selector)))

    def wait_for_present(self, by: By, selector: str):
        return self.wait.until(EC.presence_of_element_located((by, selector)))

    def wait_for_text(self, text: str) -> bool:
        self.wait.until(EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{text}')]")))
        return True

    def click_with_retry(self, by: By, selector: str, retries: int = 4):
        last_error = None
        for _ in range(retries):
            try:
                element = self.wait_for_clickable(by, selector)
                element.click()
                return
            except StaleElementReferenceException as error:
                last_error = error
                time.sleep(0.4)
        if last_error is not None:
            raise last_error


class OverleafProjectSharer(SeleniumWorkflowBase):
    def run(self) -> None:
        print("🚀 Starting Smart Overleaf Automation...")
        self.ensure_logged_in()

        recipients = self.load_recipients()
        print(f"📄 Loaded {len(recipients)} team rows from CSV.")

        for index, recipient in enumerate(recipients, start=1):
            project_name = f"{recipient.team_id} - {recipient.project_title}"
            print(
                f"\n➡️ Processing {index}/{len(recipients)}: "
                f"{project_name} -> {recipient.team_leader_email}"
            )

            self.open_project_or_template()
            self.rename_project(project_name)
            self.open_share_dialog()
            link = self.set_link_sharing_to_edit_and_copy_link()
            self.save_link_to_csv(link, project_name)
            self.send_email_via_gmail(
                recipient.team_leader_email,
                link,
                project_name,
                recipient.team_leader_name,
            )

        print(f"🏁 Done. Closing in {self.config.post_action_wait_seconds} seconds...")
        time.sleep(self.config.post_action_wait_seconds)

    def load_recipients(self) -> list[TeamRecipient]:
        csv_path = self.config.recipients_csv_path.expanduser()
        if not csv_path.is_absolute():
            csv_path = Path.cwd() / csv_path

        if not csv_path.exists():
            raise FileNotFoundError(f"Recipient CSV not found: {csv_path}")

        recipients: list[TeamRecipient] = []
        with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            for raw_row in reader:
                row = {self._normalize_header(k): (v or "").strip() for k, v in raw_row.items() if k}
                team_id = row.get("teamid", "")
                project_title = row.get("projecttitle", "")
                team_leader_name = row.get("teamleadername", "")
                team_leader_email = row.get("teamleaderemail", "")

                if not (team_id and project_title and team_leader_name and team_leader_email):
                    continue

                recipients.append(
                    TeamRecipient(
                        team_id=team_id,
                        project_title=project_title,
                        team_leader_name=team_leader_name,
                        team_leader_email=team_leader_email,
                    )
                )

        if not recipients:
            raise ValueError(
                "No valid rows found in recipient CSV. "
                "Required columns: team_id, project_title, team leader name, team leader email"
            )
        return recipients

    @staticmethod
    def _normalize_header(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())

    def ensure_logged_in(self) -> None:
        print("🔍 Checking login status...")
        self.open_page(self.config.dashboard_url)
        time.sleep(3)

        if "/login" in self.driver.current_url:
            print("🔑 Not logged in. Please log in manually now...")
            while "/login" in self.driver.current_url:
                time.sleep(self.config.login_poll_interval)
            print("✅ Login completed!")
        else:
            print("✅ Already logged in! Skipping login step.")

    def open_project_or_template(self) -> None:
        print(f"🔗 Moving to project: {self.config.project_url}")
        self.open_page(self.config.project_url)

        if "/latex/templates/" in self.config.project_url:
            self.open_template_as_project()

        self.wait_for_editor()

    def open_template_as_project(self) -> None:
        print("📄 Template page detected. Opening as template...")
        open_as_template_button = self.wait_for_clickable(
            By.XPATH,
            "//a[contains(@href, '/project/new/template/') and contains(normalize-space(.), 'Open as Template')]",
        )
        try:
            open_as_template_button.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", open_as_template_button)

    def wait_for_editor(self) -> None:
        print("⏳ Loading editor...")
        self.wait_for_clickable(By.XPATH, "//button[contains(., 'Share')]")

    def open_share_dialog(self) -> None:
        print("🔘 Clicking Share...")
        share_button = self.wait_for_clickable(By.XPATH, "//button[contains(., 'Share')]")
        share_button.click()

    def rename_project(self, new_name: str) -> None:
        if not new_name:
            return

        print(f"📝 Renaming project to: {new_name}")
        if self._current_project_name() == new_name:
            print("✅ Project name already set. Skipping rename.")
            return

        last_error = None
        for _ in range(7):
            try:
                self.click_with_retry(By.ID, "project-title-options")
                self.click_with_retry(
                    By.XPATH,
                    "//a[normalize-space(.)='Rename' or .//span[normalize-space(.)='Rename']]",
                )

                # Never type into the active element directly, because focus can land on the LaTeX editor.
                rename_input = self._find_rename_input(timeout=6)
                rename_input.click()
                rename_input.send_keys(Keys.CONTROL, "a")
                rename_input.send_keys(Keys.BACKSPACE)
                rename_input.send_keys(new_name)
                rename_input.send_keys(Keys.ENTER)
                time.sleep(1)
                if self._current_project_name() == new_name:
                    print("✅ Project renamed.")
                    return
            except Exception as error:
                last_error = error
                try:
                    rename_input = self._find_rename_input(timeout=4)
                    rename_input.click()
                    rename_input.send_keys(Keys.CONTROL, "a")
                    rename_input.send_keys(Keys.BACKSPACE)
                    rename_input.send_keys(new_name)
                    rename_input.send_keys(Keys.ENTER)
                    time.sleep(1)
                    if self._current_project_name() == new_name:
                        print("✅ Project renamed.")
                        return
                except Exception:
                    pass
                time.sleep(0.5)

        print(f"⚠️ Rename did not complete. Continuing workflow. Last error: {last_error}")

    def _find_rename_input(self, timeout: int = 6):
        selectors = [
            (By.CSS_SELECTOR, "input[aria-label*='Project' i]"),
            (By.CSS_SELECTOR, "input[placeholder*='Project' i]"),
            (By.CSS_SELECTOR, "input[id*='project' i]"),
            (By.XPATH, "//input[@type='text' and not(@aria-label='Search') and not(contains(@class,'cm-'))]"),
        ]
        return self._find_first_visible(selectors, timeout=timeout)

    def _current_project_name(self) -> str:
        try:
            name_el = self.wait_for_visible(By.CSS_SELECTOR, ".ide-redesign-toolbar-project-name")
            return name_el.text.strip()
        except Exception:
            return ""

    def set_link_sharing_to_edit_and_copy_link(self) -> str:
        print("🔗 Setting link sharing to 'Anyone with the link' and 'Can edit'...")

        self._click_turn_on_link_sharing()

        self._try_click_by_text("Anyone with this link", timeout=1.2)
        self._try_click_by_text("Anyone with the link", timeout=1.2)
        self._try_click_by_text("Link sharing", timeout=1.2)

        self._try_click_by_text("Can edit", timeout=1.2)
        self._try_click_by_text("Editable", timeout=1.2)

        self._click_copy_link_button()

        share_link = self._extract_share_link_fast()
        print(f"📋 Share link captured: {share_link}")
        return share_link

    def _click_turn_on_link_sharing(self) -> None:
        try:
            button = self._find_first_clickable(
                [
                    (
                        By.XPATH,
                        "//button[.//span[normalize-space(.)='Turn on link sharing'] or normalize-space(.)='Turn on link sharing']",
                    )
                ],
                timeout=2,
            )
            button.click()
            time.sleep(0.8)
            return
        except Exception:
            # Link sharing may already be enabled, which is acceptable.
            pass

    def _click_copy_link_button(self) -> None:
        try:
            button = self._find_first_clickable(
                [
                    (
                        By.XPATH,
                        "//div[contains(@class,'access-token-wrapper')][.//strong[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'can edit')]]//button[contains(@class,'copy-button')]",
                    )
                ],
                timeout=2,
            )
            button.click()
            time.sleep(0.2)
            return
        except Exception:
            pass

        self._try_click_by_text("Copy", timeout=1.2)

    def _extract_share_link_fast(self) -> str:
        deadline = time.time() + 2.5
        while time.time() < deadline:
            link = self._extract_share_link_quick_dom()
            if self._looks_like_overleaf_link(link):
                return link.strip()
            time.sleep(0.12)

        return self.driver.current_url

    @staticmethod
    def _looks_like_overleaf_link(value: str) -> bool:
        return bool(value and "overleaf.com" in value and ("/project/" in value or "/read/" in value))

    def _extract_share_link_quick_dom(self) -> str:
        try:
            code_elements = self.driver.find_elements(
                By.XPATH,
                "//div[contains(@class,'access-token-wrapper')][.//strong[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'can edit')]]//div[contains(@class,'access-token')]//code",
            )
            for element in code_elements:
                text = (element.text or "").strip()
                if text:
                    return text
        except Exception:
            pass

        try:
            link_inputs = self.driver.find_elements(
                By.XPATH,
                "//input[contains(@value, 'overleaf.com') and (@type='text' or @type='url')]",
            )
            for element in link_inputs:
                value = (element.get_attribute("value") or "").strip()
                if value:
                    return value
        except Exception:
            pass

        try:
            for element in self.driver.find_elements(By.XPATH, "//a[@href]"):
                href = element.get_attribute("href")
                if self._looks_like_overleaf_link(href or ""):
                    return (href or "").strip()
        except Exception:
            pass

        return ""

    def save_link_to_csv(self, share_link: str, project_name: str) -> None:
        csv_path = Path(self.config.share_links_csv_path).expanduser()
        if not csv_path.is_absolute():
            csv_path = Path.cwd() / csv_path

        csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not csv_path.exists()

        with csv_path.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            if write_header:
                writer.writerow(["timestamp", "project_name", "project_url", "share_link"])
            writer.writerow(
                [
                    datetime.now().isoformat(timespec="seconds"),
                    project_name,
                    self.driver.current_url,
                    share_link,
                ]
            )

        print(f"💾 Share link saved to CSV: {csv_path}")

    def _try_click_by_text(self, text: str, timeout: float = 1.0) -> bool:
        xpath = (
            "//*[self::button or self::a or self::span or self::div]"
            f"[contains(normalize-space(.), '{text}')]"
        )
        try:
            wait = WebDriverWait(self.driver, timeout)
            element = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            element.click()
            time.sleep(0.2)
            return True
        except Exception:
            return False

    def send_email_via_gmail(
        self,
        recipient_email: str,
        share_link: str,
        project_name: str,
        leader_name: str,
    ) -> None:
        print(f"📨 Sending Gmail message to: {recipient_email}")
        subject = self.config.email_subject_template.format(
            project_name=project_name,
            link=share_link,
            leader_name=leader_name,
        )

        current_window = self.driver.current_window_handle

        self.driver.execute_script("window.open(arguments[0], '_blank');", self.config.gmail_inbox_url)
        self.driver.switch_to.window(self.driver.window_handles[-1])
        try:
            self.ensure_gmail_logged_in()

            self.open_page(self.config.gmail_inbox_url)
            self._open_gmail_compose_modal()

            to_input = self._find_first_visible(
                [
                    (By.CSS_SELECTOR, "div[role='dialog'] textarea[name='to']"),
                    (By.CSS_SELECTOR, "div[role='dialog'] input[aria-label='To recipients']"),
                    (By.CSS_SELECTOR, "textarea[name='to']"),
                    (By.CSS_SELECTOR, "input[aria-label='To recipients']"),
                ],
                timeout=20,
            )
            to_input.click()
            to_input.send_keys(recipient_email)
            to_input.send_keys(Keys.ENTER)

            subject_input = self._find_first_visible(
                [
                    (By.CSS_SELECTOR, "div[role='dialog'] input[name='subjectbox']"),
                    (By.CSS_SELECTOR, "input[name='subjectbox']"),
                ],
                timeout=20,
            )
            subject_input.click()
            subject_input.send_keys(Keys.CONTROL, "a")
            subject_input.send_keys(Keys.BACKSPACE)
            subject_input.send_keys(subject)

            body = self._find_first_visible(
                [
                    (By.CSS_SELECTOR, "div[role='dialog'] div[aria-label='Message Body']"),
                    (By.CSS_SELECTOR, "div[role='dialog'] div[role='textbox'][aria-label='Message Body']"),
                    (By.CSS_SELECTOR, "div[aria-label='Message Body']"),
                ],
                timeout=20,
            )
            body.click()
            body.send_keys(self._build_plain_email_body(project_name, share_link, leader_name))

            send_button = self._find_first_clickable(
                [
                    (
                        By.XPATH,
                        "//div[@role='dialog']//div[@role='button' and (@data-tooltip='Send \\u202a(Ctrl-Enter)\\u202c' or @aria-label='Send \\u202a(Ctrl-Enter)\\u202c' or @data-tooltip='Send' or @aria-label='Send')]",
                    ),
                    (
                        By.XPATH,
                        "//div[@role='dialog']//div[@role='button' and contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'send')]",
                    ),
                ],
                timeout=20,
            )
            send_button.click()
            self._wait_for_gmail_sent_confirmation()
            print("✅ Gmail message sent.")
        finally:
            try:
                if len(self.driver.window_handles) > 1:
                    self.driver.close()
            finally:
                self.driver.switch_to.window(current_window)

    def _open_gmail_compose_modal(self) -> None:
        compose_button = self._find_first_clickable(
            [
                (By.CSS_SELECTOR, "div[gh='cm']"),
                (By.XPATH, "//div[@role='button' and (contains(., 'Compose') or contains(@aria-label, 'Compose'))]"),
            ],
            timeout=20,
        )
        compose_button.click()
        self._find_first_visible(
            [
                (By.CSS_SELECTOR, "div[role='dialog']"),
                (By.CSS_SELECTOR, "textarea[name='to']"),
            ],
            timeout=20,
        )

    def _wait_for_gmail_sent_confirmation(self) -> None:
        try:
            WebDriverWait(self.driver, 12).until(
                EC.visibility_of_element_located(
                    (
                        By.XPATH,
                        "//*[contains(., 'Message sent') or contains(., 'message sent')]",
                    )
                )
            )
        except Exception:
            # If Gmail toast is missed due to timing/locale, continue best-effort.
            pass

    def _find_first_visible(self, selectors: list[tuple[By, str]], timeout: int | None = None):
        wait = WebDriverWait(self.driver, timeout or self.config.wait_timeout)
        last_error = None
        for by, selector in selectors:
            try:
                return wait.until(EC.visibility_of_element_located((by, selector)))
            except Exception as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise TimeoutException("No matching visible element found.")

    def _find_first_clickable(self, selectors: list[tuple[By, str]], timeout: int | None = None):
        wait = WebDriverWait(self.driver, timeout or self.config.wait_timeout)
        last_error = None
        for by, selector in selectors:
            try:
                return wait.until(EC.element_to_be_clickable((by, selector)))
            except Exception as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise TimeoutException("No matching clickable element found.")


    def _build_plain_email_body(self, project_name: str, share_link: str, leader_name: str) -> str:
        return self.config.email_body_template.format(
            project_name=project_name,
            link=share_link,
            leader_name=leader_name,
        )

    def ensure_gmail_logged_in(self) -> None:
        print("🔍 Checking Gmail login status...")
        self.open_page(self.config.gmail_inbox_url)
        time.sleep(2)

        if not self._gmail_login_required():
            print("✅ Gmail already logged in.")
            return

        print("🔐 Not logged in to Gmail. Please log in manually in this browser tab...")
        started_at = time.time()
        while self._gmail_login_required():
            elapsed = time.time() - started_at
            if elapsed >= self.config.gmail_login_wait_seconds:
                raise TimeoutException(
                    "Timed out waiting for Gmail login in Selenium browser. "
                    "Google may block automated sign-in; try logging in once in this profile manually "
                    "or use an already signed-in profile directory."
                )
            time.sleep(self.config.login_poll_interval)

        print("✅ Gmail login completed. Session saved in browser profile.")

    def _gmail_login_required(self) -> bool:
        current_url = (self.driver.current_url or "").lower()
        if any(
            token in current_url
            for token in ["accounts.google.com", "servicelogin", "signin", "challenge"]
        ):
            return True

        if self._gmail_ready():
            return False

        try:
            sign_in_elements = self.driver.find_elements(
                By.XPATH,
                "//a[contains(@href,'ServiceLogin')] | //button[contains(.,'Sign in') or contains(.,'sign in')]",
            )
            if len(sign_in_elements) > 0:
                return True
        except Exception:
            pass

        # Unknown state should be treated as "not ready" to avoid false positive "logged in" prints.
        return True

    def _gmail_ready(self) -> bool:
        current_url = (self.driver.current_url or "").lower()
        if "mail.google.com" not in current_url:
            return False

        try:
            compose_candidates = self.driver.find_elements(
                By.XPATH,
                "//div[@role='button' and (@gh='cm' or contains(@aria-label,'Compose') or contains(.,'Compose'))]",
            )
            if len(compose_candidates) > 0:
                return True
        except Exception:
            pass

        # Fallback signal: Gmail shell is loaded and account avatar/button is present.
        try:
            avatar_candidates = self.driver.find_elements(
                By.XPATH,
                "//a[contains(@aria-label,'Google Account')] | //button[contains(@aria-label,'Google Account')]",
            )
            return len(avatar_candidates) > 0
        except Exception:
            return False

    def invite_collaborator(self, email: str) -> None:
        print(f"📧 Entering: {email}")
        email_input = self.wait_for_visible(By.CSS_SELECTOR, "input[type='email']")
        email_input.send_keys(email)
        time.sleep(1)
        email_input.send_keys(Keys.ENTER)
        print("⌨️ Email tagged.")

        print("📩 Clicking Invite...")
        time.sleep(2)
        invite_button = self.wait_for_present(
            By.CSS_SELECTOR,
            ".add-collaborator-controls button.btn-primary",
        )
        ActionChains(self.driver).move_to_element(invite_button).click().perform()

    def verify_invitation(self, email: str) -> None:
        print("⏳ Verifying...")
        try:
            self.wait_for_text(email)
            print(f"🎉 SUCCESS! {email} added.")
        except Exception:
            print("⚠️ Could not confirm list update, but click was sent.")