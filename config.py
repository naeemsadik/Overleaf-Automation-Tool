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
    def from_dict(cls, data: dict) -> "AppConfig":
        """Creates a config from a dictionary (e.g. from JSON settings)."""
        user_data_dir = Path(data.get("user_data_dir", str(Path.home() / ".overleaf_selenium_profile"))).expanduser()
        
        return cls(
            project_url=data.get("project_url", ""),
            user_data_dir=user_data_dir,
            recipients_csv_path=Path(data.get("recipients_csv_path", "data.csv")),
            target_email=data.get("target_email"),
            desired_project_name=data.get("desired_project_name", "Autmatic Send"),
            share_links_csv_path=Path(data.get("share_links_csv_path", "overleaf_share_links.csv")),
            gmail_compose_url=data.get("gmail_compose_url", "https://mail.google.com/mail/u/0/#inbox?compose=new"),
            gmail_inbox_url=data.get("gmail_inbox_url", "https://mail.google.com/mail/u/0/#inbox"),
            gmail_login_wait_seconds=int(data.get("gmail_login_wait_seconds", 300)),
            email_subject_template=data.get("email_subject_template", "Overleaf Project Edit Access: {project_name}"),
            email_body_template=data.get("email_body_template", 
                "Dear {leader_name},\n\n"
                "I hope you are doing well. I am sharing the Overleaf project {project_name} with edit access.\n\n"
                "Project details:\n"
                "Project: {project_name}\n"
                "Access: Can edit\n"
                "Link: {link}\n\n"
                "Please share this link with the other members of your team.\n\n"
                "Please use the link above to open the project.\n\n"
                "Regards,\n"
                "Overleaf Automation"
            ).replace("\\n", "\n"),
            wait_timeout=int(data.get("wait_timeout", 15)),
            login_poll_interval=float(data.get("login_poll_interval", 1.0)),
            post_action_wait_seconds=int(data.get("post_action_wait_seconds", 5)),
            start_maximized=data.get("start_maximized", True)
        )

    @classmethod
    def from_environment(cls) -> "AppConfig":
        load_dotenv(find_dotenv())
        
        # We reuse the logic by creating a dict from env vars
        env_dict = {
            "project_url": os.getenv("OVERLEAF_PROJECT_URL"),
            "user_data_dir": os.getenv("SELENIUM_USER_DATA_DIR"),
            "recipients_csv_path": os.getenv("OVERLEAF_RECIPIENTS_CSV"),
            "target_email": os.getenv("OVERLEAF_TARGET_EMAIL"),
            "desired_project_name": os.getenv("OVERLEAF_PROJECT_NAME"),
            "share_links_csv_path": os.getenv("OVERLEAF_SHARE_LINK_CSV"),
            "gmail_compose_url": os.getenv("GMAIL_COMPOSE_URL"),
            "gmail_inbox_url": os.getenv("GMAIL_INBOX_URL"),
            "gmail_login_wait_seconds": os.getenv("GMAIL_LOGIN_WAIT_SECONDS"),
            "email_subject_template": os.getenv("EMAIL_SUBJECT_TEMPLATE"),
            "email_body_template": os.getenv("EMAIL_BODY_TEMPLATE"),
            "wait_timeout": os.getenv("OVERLEAF_WAIT_TIMEOUT"),
            "login_poll_interval": os.getenv("OVERLEAF_LOGIN_POLL_INTERVAL"),
            "post_action_wait_seconds": os.getenv("OVERLEAF_POST_ACTION_WAIT_SECONDS"),
        }
        # Clean None values so defaults are used
        env_dict = {k: v for k, v in env_dict.items() if v is not None}
        
        # Validation for required fields only if using env
        if "project_url" not in env_dict:
            raise ValueError("Missing required environment variable: OVERLEAF_PROJECT_URL")
            
        return cls.from_dict(env_dict)

def _required_env(name: str) -> str:
    # Kept for backward compatibility if needed, but not used in new flow
    value = os.getenv(name)
    if not value:
        raise ValueError(
            f"Missing required environment variable: {name}. "
            f"Create a .env file based on .env.example and set {name}."
        )
    return value