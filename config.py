from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class AppConfig:
    project_url: str
    user_data_dir: Path
    recipients_csv_path: Path = Path("data.csv")
    target_email: str | None = None
    desired_project_name: str = "Autmatic Send"
    share_links_csv_path: Path = Path("overleaf_share_links.csv")
    gmail_compose_url: str = "https://mail.google.com/mail/u/0/#inbox?compose=new"
    gmail_inbox_url: str = "https://mail.google.com/mail/u/0/#inbox"
    gmail_login_wait_seconds: int = 300
    email_subject_template: str = "Overleaf Project Edit Access: {project_name}"
    email_body_template: str = (
        "Dear {leader_name},\n\n"
        "I hope you are doing well. I am sharing the Overleaf project {project_name} with edit access.\n\n"
        "Project details:\n"
        "Project: {project_name}\n"
        "Access: Can edit\n"
        "Link: {link}\n\n"
        "Please share this link with the other members of your team.\n\n"
        "Please use the link above to open the project.\n\n"
        "Regards,\n"
        "Naeem Abdullah Sadik"
    )
    dashboard_url: str = "https://www.overleaf.com/project"
    wait_timeout: int = 15
    login_poll_interval: float = 1.0
    post_action_wait_seconds: int = 5
    start_maximized: bool = True

    @classmethod
    def from_environment(cls) -> "AppConfig":
        load_dotenv(find_dotenv())

        project_url = _required_env("OVERLEAF_PROJECT_URL")
        user_data_dir = Path(
            os.getenv(
                "SELENIUM_USER_DATA_DIR",
                str(Path.home() / ".overleaf_selenium_profile"),
            )
        ).expanduser()

        return cls(
            project_url=project_url,
            user_data_dir=user_data_dir,
            recipients_csv_path=Path(os.getenv("OVERLEAF_RECIPIENTS_CSV", "data.csv")),
            target_email=os.getenv("OVERLEAF_TARGET_EMAIL"),
            desired_project_name=os.getenv("OVERLEAF_PROJECT_NAME", "Autmatic Send"),
            share_links_csv_path=Path(
                os.getenv("OVERLEAF_SHARE_LINK_CSV", "overleaf_share_links.csv")
            ),
            gmail_compose_url=os.getenv(
                "GMAIL_COMPOSE_URL",
                "https://mail.google.com/mail/u/0/#inbox?compose=new",
            ),
            gmail_inbox_url=os.getenv(
                "GMAIL_INBOX_URL",
                "https://mail.google.com/mail/u/0/#inbox",
            ),
            gmail_login_wait_seconds=int(os.getenv("GMAIL_LOGIN_WAIT_SECONDS", "300")),
            email_subject_template=os.getenv(
                "EMAIL_SUBJECT_TEMPLATE",
                "Overleaf Project Edit Access",
            ),
            email_body_template=os.getenv(
                "EMAIL_BODY_TEMPLATE",
                "Dear {leader_name},\n\n"
                "I hope you are doing well. I am sharing the Overleaf project {project_name} with edit access.\n\n"
                "Project details:\n"
                "Project: {project_name}\n"
                "Access: Can edit\n"
                "Link: {link}\n\n"
                "Please share this link with the other members of your team.\n\n"
                "Please use the link above to open the project.\n\n"
                "Regards,\n"
                "Overleaf Automation",
            ).replace("\\n", "\n"),
            wait_timeout=int(os.getenv("OVERLEAF_WAIT_TIMEOUT", "15")),
            login_poll_interval=float(os.getenv("OVERLEAF_LOGIN_POLL_INTERVAL", "1")),
            post_action_wait_seconds=int(
                os.getenv("OVERLEAF_POST_ACTION_WAIT_SECONDS", "5")
            ),
        )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(
            f"Missing required environment variable: {name}. "
            f"Create a .env file based on .env.example and set {name}."
        )
    return value