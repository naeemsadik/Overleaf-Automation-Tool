import time
import csv
import ctypes
import re
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

# Overleaf project names: keep readable, strip characters that break rename/UI.
_INVALID_PROJECT_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_PROJECT_NAME_LEN = 150
_HEADER_TEAM_ID_VALUES = frozenset({"teamid", "groupname", "team_id", "group_name"})


class ManualLoginRequired(RuntimeError):
    """Raised when a manual browser login is required during automation."""
    pass


@dataclass(frozen=True)
class TeamMember:
    name: str
    email: str
    student_id: str


@dataclass(frozen=True)
class TeamRecipient:
    team_id: str
    project_title: str
    supervisor_name: str
    members: list[TeamMember]
    cc_emails: list[str]


class SeleniumWorkflowBase:
    def __init__(self, driver, config: AppConfig, stop_event=None) -> None:
        self.driver = driver
        self.config = config
        self.stop_event = stop_event
        self.wait = WebDriverWait(driver, config.wait_timeout)

    def open_page(self, url: str) -> None:
        self.driver.get(url)

    def wait_for_clickable(self, by: By, selector: str, timeout: int | None = None):
        wait = WebDriverWait(self.driver, timeout) if timeout is not None else self.wait
        return wait.until(EC.element_to_be_clickable((by, selector)))

    def wait_for_visible(self, by: By, selector: str, timeout: int | None = None):
        wait = WebDriverWait(self.driver, timeout) if timeout is not None else self.wait
        return wait.until(EC.visibility_of_element_located((by, selector)))

    def wait_for_present(self, by: By, selector: str, timeout: int | None = None):
        wait = WebDriverWait(self.driver, timeout) if timeout is not None else self.wait
        return wait.until(EC.presence_of_element_located((by, selector)))

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
    class ManualLoginRequired(RuntimeError):
        pass

    def run(self) -> None:
        print("🚀 Starting Smart Overleaf Automation...")
        # Note: Initial login check is handled by the caller/manager to support headless transition
        
        recipients = self.load_recipients()
        print(f"📄 Loaded {len(recipients)} team groups from CSV.")

        for index, recipient in enumerate(recipients, start=1):
            if self.stop_event and self.stop_event.is_set():
                print("\n🛑 Stop signal detected. Breaking automation loop...")
                break

            project_name = self.build_project_name(recipient)
            if not project_name:
                print(f"\n⚠️ Skipping team with empty/invalid team id at index {index}.")
                continue
            if not recipient.members:
                print(f"\n⚠️ Skipping {project_name}: no member emails found.")
                continue

            member_names = ", ".join([m.name for m in recipient.members])
            print(
                f"\n➡️ Processing {index}/{len(recipients)}: "
                f"{project_name} -> [{member_names}]"
            )

            self.open_project_or_template()
            self.rename_project(project_name)
            self.open_share_dialog()
            link = self.set_link_sharing_to_edit_and_copy_link()
            self.save_link_to_csv(link, project_name)
            self.send_email_via_gmail(
                recipient=recipient,
                share_link=link,
                project_name=project_name
            )

        print(f"🏁 Done. Closing in {self.config.post_action_wait_seconds} seconds...")
        time.sleep(self.config.post_action_wait_seconds)

    def build_project_name(self, recipient: TeamRecipient) -> str:
        """Overleaf project name is the team/group id only (e.g. 261-001)."""
        return self._sanitize_project_name(recipient.team_id)

    @classmethod
    def _sanitize_project_name(cls, raw: str) -> str:
        name = (raw or "").strip()
        if not name:
            return ""
        name = _INVALID_PROJECT_NAME_CHARS.sub("-", name)
        name = re.sub(r"\s+", " ", name).strip(" .-_")
        if len(name) > _MAX_PROJECT_NAME_LEN:
            name = name[:_MAX_PROJECT_NAME_LEN].rstrip(" .-_")
        return name

    def load_recipients(self) -> list[TeamRecipient]:
        csv_path = self.config.recipients_csv_path.expanduser()
        if not csv_path.is_absolute():
            csv_path = Path.cwd() / csv_path

        if not csv_path.exists():
            raise FileNotFoundError(f"Recipient CSV not found: {csv_path}")

        recipients: list[TeamRecipient] = []
        with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            
            current_team_id = None
            current_project_title = None
            current_members = []
            current_cc = []
            current_supervisor = ""

            for raw_row in reader:
                # Normalize keys for robustness
                row = {self._normalize_header(k): (v or "").strip() for k, v in raw_row.items() if k}
                
                # Support multiple CSV header variants: legacy 'teamid'/'projecttitle',
                # and newer 'groupname'/'title'. Also support 'members' + 'memberemails'.
                team_id = (row.get("teamid", "") or row.get("groupname", "")).strip()
                project_title = row.get("projecttitle", "") or row.get("title", "")
                supervisor_name = row.get("supervisor", "")

                # Member name(s) can be in 'teammembers' or 'members'; emails in 'emails' or 'memberemails'
                member_cell = row.get("teammembers", "") or row.get("members", "") or row.get("teamleadername", "")
                member_email_cell = row.get("emails", "") or row.get("memberemails", "") or row.get("teamleaderemail", "")
                student_id = row.get("studentid", "")
                cc_val = row.get("cc", "") or row.get("supervisoremail", "")

                # Normalize member names: many exports include IDs with names in parentheses,
                # e.g. "011222086 (Alisha Johura), 011212001 (Abu Henaf...)". Extract names inside parentheses.
                member_names = []
                if member_cell:
                    # find names in parentheses
                    paren_names = re.findall(r"\(([^)]+)\)", member_cell)
                    if paren_names:
                        member_names = [n.strip() for n in paren_names if n.strip()]
                    else:
                        # fallback: split on commas
                        member_names = [m.strip() for m in member_cell.split(",") if m.strip()]

                # Normalize emails: may be comma/semicolon/newline-separated.
                member_emails = self._split_email_list(member_email_cell)

                # Skip true header rows if they somehow ended up in data
                if self._normalize_header(team_id) in _HEADER_TEAM_ID_VALUES:
                    continue

                if team_id:
                    # Save previous team if exists
                    if current_team_id:
                        recipients.append(TeamRecipient(
                            team_id=current_team_id,
                            project_title=current_project_title,
                            supervisor_name=current_supervisor,
                            members=current_members,
                            cc_emails=current_cc
                        ))
                    
                    # Start new team
                    current_team_id = team_id
                    current_project_title = project_title or "Untitled"
                    current_members = []
                    current_cc = []
                    current_supervisor = supervisor_name or "Supervisor"

                if not current_team_id:
                    # Orphan member/email rows with no team id yet — ignore safely
                    continue

                if supervisor_name and not current_supervisor:
                    current_supervisor = supervisor_name

                # Pair parsed member names with emails (if available). If counts differ,
                # fill missing names with empty string and still include emails.
                max_count = max(len(member_names), len(member_emails))
                for i in range(max_count):
                    name = member_names[i] if i < len(member_names) else ""
                    email = member_emails[i] if i < len(member_emails) else ""
                    if email and "@" in email:
                        current_members.append(TeamMember(name=name or email, email=email, student_id=student_id))

                if cc_val:
                    # Split by comma or semicolon if multiple CCs in one cell
                    ccs = self._split_email_list(cc_val)
                    for c in ccs:
                        if c not in current_cc and "@" in c:
                            current_cc.append(c)

            # Add last team
            if current_team_id:
                recipients.append(TeamRecipient(
                    team_id=current_team_id,
                    project_title=current_project_title,
                    supervisor_name=current_supervisor,
                    members=current_members,
                    cc_emails=current_cc
                ))

        recipients = self._finalize_recipients(recipients)

        if not recipients:
            # Read a small sample of the CSV to help debugging
            sample_lines = []
            try:
                with csv_path.open("r", encoding="utf-8-sig", errors="replace") as f:
                    for _ in range(10):
                        line = f.readline()
                        if not line:
                            break
                        sample_lines.append(line.strip())
            except Exception:
                sample_lines = ["(could not read sample lines)"]

            # Detect headers present in the file
            detected_headers = []
            try:
                with csv_path.open("r", encoding="utf-8-sig", errors="replace") as f:
                    header_line = f.readline()
                    detected_headers = [h.strip() for h in header_line.split(",") if h.strip()]
            except Exception:
                detected_headers = []

            detail = (
                f"No valid teams found in recipient CSV: {csv_path}\n"
                f"Detected headers: {detected_headers}\n"
                f"Sample lines (up to 10):\n" + "\n".join(sample_lines)
            )
            raise ValueError(detail)
        return recipients

    def _finalize_recipients(self, recipients: list[TeamRecipient]) -> list[TeamRecipient]:
        """Drop invalid/duplicate teams and warn about edge cases before automation runs."""
        finalized: list[TeamRecipient] = []
        seen_names: dict[str, str] = {}

        for recipient in recipients:
            project_name = self._sanitize_project_name(recipient.team_id)
            if not project_name:
                print(f"⚠️ Skipping team with empty/invalid team id (title={recipient.project_title!r}).")
                continue

            # Deduplicate members by email (case-insensitive) within the team
            deduped_members: list[TeamMember] = []
            seen_emails: set[str] = set()
            for member in recipient.members:
                key = member.email.strip().lower()
                if not key or key in seen_emails:
                    continue
                seen_emails.add(key)
                deduped_members.append(member)

            name_key = project_name.casefold()
            if name_key in seen_names:
                print(
                    f"⚠️ Duplicate team id {project_name!r} "
                    f"(also seen as {seen_names[name_key]!r}). Skipping duplicate row group."
                )
                continue
            seen_names[name_key] = project_name

            if not deduped_members:
                print(f"⚠️ Team {project_name} has no valid member emails. It will be skipped at run time.")

            finalized.append(
                TeamRecipient(
                    team_id=project_name,
                    project_title=recipient.project_title,
                    supervisor_name=recipient.supervisor_name,
                    members=deduped_members,
                    cc_emails=recipient.cc_emails,
                )
            )

        return finalized

    @staticmethod
    def _normalize_header(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())

    @staticmethod
    def _split_email_list(value: str) -> list[str]:
        parts = re.split(r"[;,\n]+", value or "")
        return [part.strip() for part in parts if part.strip()]

    def ensure_logged_in(self) -> bool:
        """Returns True if manual login was required and performed."""
        print("🔍 Checking Overleaf login status...")
        self.open_page(self.config.dashboard_url)
        
        # dynamic wait instead of sleep(3)
        try:
            self.wait_for_visible(By.XPATH, "//button[contains(., 'Project') or contains(., 'New Project') or contains(@class, 'user-menu')]", timeout=8)
        except:
            pass

        if "/login" in self.driver.current_url:
            print("🔑 Overleaf: Not logged in. Please log in manually now...")
            while "/login" in self.driver.current_url:
                time.sleep(self.config.login_poll_interval)
            print("✅ Overleaf login completed!")
            return True # Login was required
        else:
            print("✅ Overleaf: Already logged in.")
            return False

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

        template_href = ""
        try:
            template_href = (open_as_template_button.get_attribute("href") or "").strip()
        except Exception:
            template_href = ""

        if template_href:
            self.open_page(template_href)
            return

        try:
            open_as_template_button.click()
        except Exception:
            try:
                self.driver.execute_script("arguments[0].click();", open_as_template_button)
            except Exception:
                # Last resort: navigate to the current element target via JS location.
                if template_href:
                    self.open_page(template_href)

    def wait_for_editor(self) -> None:
        print("⏳ Loading editor...")
        self.wait_for_clickable(By.XPATH, "//button[contains(., 'Share')]")

    def open_share_dialog(self) -> None:
        print("🔘 Clicking Share...")
        share_button = self.wait_for_clickable(By.XPATH, "//button[contains(., 'Share')]")
        share_button.click()

    def rename_project(self, new_name: str) -> None:
        new_name = self._sanitize_project_name(new_name)
        if not new_name:
            print("⚠️ Empty project name after sanitization. Skipping rename.")
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
                rename_input = self._find_rename_input(timeout=5)
                rename_input.click()
                rename_input.send_keys(Keys.CONTROL, "a")
                rename_input.send_keys(Keys.BACKSPACE)
                rename_input.send_keys(new_name)
                rename_input.send_keys(Keys.ENTER)
                
                # Dynamic wait for name change
                deadline = time.time() + 3
                while time.time() < deadline:
                    if self._current_project_name() == new_name:
                        print("✅ Project renamed.")
                        return
                    time.sleep(0.3)
                    
            except Exception as error:
                last_error = error
                time.sleep(0.3)

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
        if not self._looks_like_share_token_link(share_link):
            raise RuntimeError(
                "Could not capture an Overleaf share link. "
                "Link sharing may not be enabled, or Overleaf UI changed. "
                f"Last candidate: {share_link!r}"
            )
        print(f"📋 Share link captured: {share_link}")
        return share_link

    @classmethod
    def _looks_like_share_token_link(cls, value: str) -> bool:
        """True for share/read token links; false for editor/dashboard URLs."""
        if not cls._looks_like_overleaf_link(value):
            return False
        text = value.strip().lower()
        path = text.split("overleaf.com/", 1)[-1].split("?", 1)[0].strip("/")
        if not path:
            return False
        # Editor / project pages must never be emailed as "share links".
        if path.startswith("project/") or path.startswith("latex/") or path.startswith("docs"):
            return False
        return True

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
            time.sleep(0.4)
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
            if self._looks_like_share_token_link(link):
                return link.strip()
            time.sleep(0.12)

        return (self.driver.current_url or "").strip()

    @staticmethod
    def _looks_like_overleaf_link(value: str) -> bool:
        if not value or "overleaf.com" not in value:
            return False
        # Accept short links (e.g., overleaf.com/123xyz) or project/read links
        return "/" in value.split("overleaf.com/")[1] or len(value.split("overleaf.com/")[1]) > 5

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
        recipient: TeamRecipient,
        share_link: str,
        project_name: str,
    ) -> None:
        all_emails = self._dedupe_emails([m.email for m in recipient.members])
        cc_emails = self._dedupe_emails(recipient.cc_emails)
        cc_emails = [email for email in cc_emails if email not in all_emails]

        if not all_emails:
            raise ValueError(
                f"Cannot send email for project {project_name!r}: no valid member emails."
            )

        print(f"📨 Sending Gmail message to: {', '.join(all_emails)}")
        if cc_emails:
            print(f"📎 CC: {', '.join(cc_emails)}")

        subject = self.config.email_subject_template.format(
            project_name=project_name,
            link=share_link,
            # For backward compatibility if someone used {leader_name} in subject
            leader_name=recipient.members[0].name if recipient.members else "Team"
        )

        current_window = None
        try:
            current_window = self.driver.current_window_handle
        except Exception:
            current_window = None

        # Try to open Gmail in a Selenium-managed new tab where possible.
        try:
            try:
                self.driver.switch_to.new_window('tab')
                self.open_page(self.config.gmail_inbox_url)
            except Exception:
                self.driver.execute_script("window.open(arguments[0], '_blank');", self.config.gmail_inbox_url)
                self.driver.switch_to.window(self.driver.window_handles[-1])
        except Exception:
            # Fall back to opening in the current window if tab creation fails.
            try:
                self.open_page(self.config.gmail_inbox_url)
            except Exception:
                pass
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
            self._fill_gmail_recipients(to_input, all_emails)

            if cc_emails:
                cc_input = self._ensure_gmail_cc_input()
                cc_input.click()
                self._fill_gmail_recipients(cc_input, cc_emails)

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

            body_el = self._find_first_visible(
                [
                    (By.CSS_SELECTOR, "div[role='dialog'] div[aria-label='Message Body']"),
                    (By.CSS_SELECTOR, "div[role='dialog'] div[role='textbox'][aria-label='Message Body']"),
                    (By.CSS_SELECTOR, "div[aria-label='Message Body']"),
                ],
                timeout=20,
            )
            body_el.click()
            body_content = self._build_plain_email_body(recipient, share_link, project_name)
            body_el.send_keys(body_content)

            self._send_gmail_message_with_confirmation(body_el)
            print("✅ Gmail message sent.")
        finally:
            # Close the Gmail tab if present and switch back to the original window.
            try:
                if current_window and len(self.driver.window_handles) > 1:
                    try:
                        self.driver.close()
                    except Exception:
                        pass
                    try:
                        self.driver.switch_to.window(current_window)
                    except Exception:
                        # If original window handle is gone, switch to any available window.
                        try:
                            if self.driver.window_handles:
                                self.driver.switch_to.window(self.driver.window_handles[0])
                        except Exception:
                            pass
            except Exception:
                pass

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

    def _send_gmail_message_with_confirmation(self, body_el) -> None:
        initial_compose_count = self._count_open_compose_dialogs()

        selectors = [
            (
                By.XPATH,
                "(//div[@role='dialog'])[last()]//div[@role='button' and (@data-tooltip='Send \\u202a(Ctrl-Enter)\\u202c' or @aria-label='Send \\u202a(Ctrl-Enter)\\u202c' or @data-tooltip='Send' or @aria-label='Send')]",
            ),
            (
                By.XPATH,
                "(//div[@role='dialog'])[last()]//div[@role='button' and contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'send')]",
            ),
            (
                By.XPATH,
                "(//div[@role='dialog'])[last()]//*[@role='button' and (contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'send') or contains(translate(@data-tooltip,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'send') or contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'send'))]",
            ),
        ]

        sent = False
        try:
            send_button = self._find_first_clickable(selectors, timeout=20)
            try:
                send_button.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", send_button)
            sent = self._wait_for_gmail_send_outcome(timeout=12, initial_compose_count=initial_compose_count)
        except Exception:
            sent = False

        if sent:
            return

        # Fallback: Gmail keyboard shortcut for send.
        # Avoid hard-clicking the body because Gmail overlays can intercept it.
        try:
            active = self.driver.switch_to.active_element
            active.send_keys(Keys.CONTROL, Keys.ENTER)
        except Exception:
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys(Keys.ENTER).key_up(Keys.CONTROL).perform()
        if self._wait_for_gmail_send_outcome(timeout=12, initial_compose_count=initial_compose_count):
            return

        # Last attempt: direct shortcut on compose body element if available.
        try:
            body_el.send_keys(Keys.CONTROL, Keys.ENTER)
        except Exception:
            pass
        if self._wait_for_gmail_send_outcome(timeout=12, initial_compose_count=initial_compose_count):
            return

        raise RuntimeError(
            "Gmail did not confirm sending the message. It may have remained in Drafts."
        )

    def _wait_for_gmail_send_outcome(self, timeout: int, initial_compose_count: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._wait_for_gmail_sent_confirmation(timeout=1):
                return True

            # In many Gmail variants, the compose dialog closes immediately on successful send.
            if self._count_open_compose_dialogs() < initial_compose_count:
                return True

            time.sleep(0.2)

        return False

    def _wait_for_gmail_sent_confirmation(self, timeout: int = 12) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_element_located(
                    (
                        By.XPATH,
                        "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'message sent')]",
                    )
                )
            )
            return True
        except Exception:
            return False

    def _count_open_compose_dialogs(self) -> int:
        try:
            dialogs = self.driver.find_elements(
                By.XPATH,
                "//div[@role='dialog'][.//input[@name='subjectbox'] or .//div[@aria-label='Message Body'] or .//textarea[@name='to']]",
            )
            return len(dialogs)
        except Exception:
            return 0

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

    @staticmethod
    def _dedupe_emails(emails: list[str]) -> list[str]:
        seen = set()
        deduped: list[str] = []
        for email in emails:
            normalized = (email or "").strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _fill_gmail_recipients(self, to_input, recipient_emails: list[str]) -> None:
        for email in recipient_emails:
            to_input.send_keys(email)
            to_input.send_keys(Keys.ENTER)
            time.sleep(0.05)

    def _ensure_gmail_cc_input(self):
        cc_input_selectors = [
            (By.CSS_SELECTOR, "div[role='dialog'] textarea[name='cc']"),
            (By.CSS_SELECTOR, "div[role='dialog'] input[aria-label='Cc recipients']"),
            (By.CSS_SELECTOR, "textarea[name='cc']"),
            (By.CSS_SELECTOR, "input[aria-label='Cc recipients']"),
        ]

        try:
            return self._find_first_visible(cc_input_selectors, timeout=2)
        except Exception:
            pass

        cc_button = self._find_first_clickable(
            [
                (By.XPATH, "//span[normalize-space(.)='Cc']"),
                (By.XPATH, "//div[@role='dialog']//span[normalize-space(.)='Cc']"),
                (
                    By.XPATH,
                    "//div[@role='dialog']//*[contains(@aria-label,'Cc') and (self::span or self::div or self::button)]",
                ),
            ],
            timeout=6,
        )
        cc_button.click()
        return self._find_first_visible(cc_input_selectors, timeout=6)


    def _build_plain_email_body(self, recipient: TeamRecipient, share_link: str, project_name: str) -> str:
        member_list_str = "\n".join([f"- {m.name} ({m.email})" for m in recipient.members])
        
        # We try to use the leader name if it was in the template, otherwise first member
        leader_name = recipient.members[0].name if recipient.members else "Team"
        
        body = self.config.email_body_template.format(
            project_name=project_name,
            link=share_link,
            leader_name=leader_name,
            team_members=member_list_str # New placeholder
        )
        
        # If the user didn't have {team_members} in their template yet, we append it
        if "{team_members}" not in self.config.email_body_template:
            body += f"\n\nTeam Members:\n{member_list_str}"
            
        return body

    @staticmethod
    def _set_clipboard_text(text: str) -> None:
        try:
            CF_UNICODETEXT = 13
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            if not user32.OpenClipboard(None):
                return
            try:
                user32.EmptyClipboard()
                data = (text + "\x00").encode("utf-16le")
                handle = kernel32.GlobalAlloc(0x0002, len(data))
                if not handle:
                    return
                pointer = kernel32.GlobalLock(handle)
                if not pointer:
                    return
                try:
                    ctypes.memmove(pointer, data, len(data))
                finally:
                    kernel32.GlobalUnlock(handle)
                user32.SetClipboardData(CF_UNICODETEXT, handle)
            finally:
                user32.CloseClipboard()
        except Exception:
            pass

    def ensure_gmail_logged_in(self) -> None:
        print("🔍 Checking Gmail login status...")
        self.open_page(self.config.gmail_inbox_url)

        # Wait briefly for the page to settle before checking login state
        try:
            WebDriverWait(self.driver, 5).until(
                lambda d: d.current_url and d.current_url != "about:blank"
            )
        except Exception:
            pass

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
        try:
            current_url = (self.driver.current_url or "").lower()
        except Exception:
            # If the window is closed or inaccessible, treat as login required.
            return True

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
        try:
            current_url = (self.driver.current_url or "").lower()
        except Exception:
            return False

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