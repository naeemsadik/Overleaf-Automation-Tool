from pathlib import Path
from datetime import datetime
import time

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.options import Options


# The real Chrome user data directory — Selenium cannot share this with a running Chrome.
_REAL_CHROME_PROFILE = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
# Dedicated profile directory for LeafPilot automation.
_LEAFPILOT_PROFILE = Path.home() / ".leafpilot_chrome_profile"


def _safe_profile_dir(requested: Path) -> Path:
    """
    If the user configured the real Chrome profile directory, silently redirect
    to the dedicated LeafPilot profile so we never fight with a running Chrome.
    """
    try:
        if requested.resolve() == _REAL_CHROME_PROFILE.resolve():
            return _LEAFPILOT_PROFILE
    except Exception:
        pass
    return requested


class ChromeBrowserManager:
    def __init__(
        self,
        user_data_dir: Path,
        start_maximized: bool = True,
        allow_profile_fallback: bool = False,
    ) -> None:
        self.user_data_dir = _safe_profile_dir(Path(user_data_dir))
        self.start_maximized = start_maximized
        self.allow_profile_fallback = allow_profile_fallback
        self._active_user_data_dir = self.user_data_dir

    def create_driver(self, headless: bool = False) -> webdriver.Chrome:
        self._active_user_data_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_profile_locks(self._active_user_data_dir)

        active_profile_dir = None

        last_error: Exception | None = None
        for attempt in range(3):
            options = self._build_options(headless=headless, attempt=attempt, profile_dir=active_profile_dir)
            try:
                # Selenium 4.6+ includes selenium-manager which auto-resolves
                # the correct chromedriver without any network calls.
                return webdriver.Chrome(options=options)
            except Exception as error:
                last_error = error
                if not self._is_startup_crash(error):
                    raise

                if (
                    self.allow_profile_fallback
                    and not headless
                    and self._active_user_data_dir == self.user_data_dir
                ):
                    self._active_user_data_dir = self._build_fallback_profile_dir()
                    self._active_user_data_dir.mkdir(parents=True, exist_ok=True)

                self._cleanup_stale_profile_locks(self._active_user_data_dir)

                # Brief pause between retries to let Chrome release the profile lock.
                time.sleep(0.75)

        if last_error is not None:
            raise last_error
        raise SessionNotCreatedException("Unable to create browser driver.")

    def _build_options(self, headless: bool, attempt: int = 0, profile_dir: str | None = None) -> Options:
        options = Options()
        if self.start_maximized and not headless:
            options.add_argument("--start-maximized")

        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--remote-debugging-port=0")
            options.add_argument("--remote-debugging-pipe")

        options.add_argument(f"--user-data-dir={self._active_user_data_dir}")
        if profile_dir:
            options.add_argument(f"--profile-directory={profile_dir}")
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # On retries, reduce the chance of startup collisions by avoiding extra flags.
        if attempt >= 1 and not headless:
            options.add_argument("--disable-extensions")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")

        return options

    @staticmethod
    def _is_startup_crash(error: Exception) -> bool:
        text = str(error).lower()
        return (
            isinstance(error, SessionNotCreatedException)
            or "devtoolsactiveport" in text
            or "chrome failed to start" in text
            or "session not created" in text
            or "chrome crashed" in text
        )

    @staticmethod
    def _cleanup_stale_profile_locks(profile_dir: Path) -> None:
        lock_names = [
            "SingletonLock",
            "SingletonSocket",
            "SingletonCookie",
            "DevToolsActivePort",
        ]
        for name in lock_names:
            try:
                path = profile_dir / name
                if path.exists():
                    path.unlink()
            except Exception:
                pass

    def _build_fallback_profile_dir(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.user_data_dir.parent / f"{self.user_data_dir.name}_leafpilot_{timestamp}"

    @staticmethod
    def quit_driver(driver: webdriver.Chrome | None) -> None:
        if driver is not None:
            try:
                driver.quit()
                # give Chrome a short moment to fully terminate to avoid races
                # when launching a new visible browser immediately after quitting
                try:
                    time.sleep(0.35)
                except Exception:
                    pass
            except Exception:
                # Driver/session may already be terminated by browser crash or manual close.
                pass