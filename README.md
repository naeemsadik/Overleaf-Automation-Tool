# Overleaf Automation Tool

This project opens an Overleaf project/template for each row in an input CSV, renames each created project, enables edit link sharing, exports links to CSV, and sends the link using Gmail.

## Setup

1. Create a virtual environment if you want one.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Copy [.env.example](.env.example) to `.env` and fill in your values.

## Environment Variables

- `OVERLEAF_PROJECT_URL`: either an Overleaf project URL (for existing projects) or a template URL (the script clicks Open as Template automatically).
- `OVERLEAF_RECIPIENTS_CSV`: input CSV path with team rows.
- `OVERLEAF_PROJECT_NAME`: project name to set after opening the project.
- `OVERLEAF_SHARE_LINK_CSV`: output CSV file path for saved share links.
- `GMAIL_COMPOSE_URL`: Gmail compose URL used by the automation.
- `GMAIL_INBOX_URL`: Gmail inbox URL used to verify login status before composing.
- `GMAIL_LOGIN_WAIT_SECONDS`: max wait time for manual Gmail login in Selenium browser.
- `EMAIL_SUBJECT_TEMPLATE`: subject line for the outgoing email. Use `{project_name}` and `{link}` placeholders if desired.
- `EMAIL_BODY_TEMPLATE`: plain text email body template. Use `{leader_name}`, `{project_name}`, and `{link}` placeholders.
- `SELENIUM_USER_DATA_DIR`: a dedicated Chrome profile folder for storing your login session.

## CSV Format

Input CSV must include these columns (case/spacing can vary):

- `team_id`
- `project_title`
- `team leader name`
- `team leader email`

Each row creates one project named `team_id - project_title` and sends one email to that row's team leader.

## Run

```powershell
python main.py
```

## Notes

- Do not use `pip install .\requirements.txt`; use `pip install -r requirements.txt` instead.
- Close any other Chrome windows that use the same profile folder before running the script.
