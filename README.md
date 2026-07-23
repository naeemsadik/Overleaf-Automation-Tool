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

Input CSV supports three formats (case/spacing can vary):

- Old single-row format:
	- `team_id`
	- `project_title`
	- `team leader name`
	- `team leader email`
- New grouped format:
	- `team_id`
	- `project_title`
	- `team_members`
	- `emails`
- Updated format:
	- `group name`
	- `title`
	- `members`
	- `member emails`
	- `supervisor`
	- `supervisor email` (optional; used for Gmail CC)

In the new grouped format, the first row of a team contains `team_id` and `project_title`, and following rows for that team can leave those fields blank while providing additional `team_members` and `emails`. The script groups rows by team and sends one email per team to all collected member emails.

Project naming uses the team/group id only (for example `261-001`). Title and supervisor are not included in the Overleaf project name.

## Run

```powershell
python main.py
```

The app opens a simple PyQt window where you can pick the recipients CSV and start the automation. Chrome runs headless by default, and only opens visibly if Overleaf or Gmail requires manual login.

UI notes:

- Main UI theme color: `#f08801`.
- Footer includes a black background with copyright text for UIU Computer Club Programming Department.
- Circular logo and app icon use `ccl_pd.jpeg` (fallbacks: `logo.png`, `assets/ccl_pd.jpeg`, `assets/logo.png`). If no image is found, a branded fallback circle is shown.

Team member handling:

- Team size is not limited. Fewer than 5 or more than 5 members are both supported.
- All valid email addresses found in each team's rows are collected and deduplicated.
- One Gmail message is sent per team to all collected member emails.

## Build EXE (Windows)

1. Activate your environment.
2. Run:

```powershell
./build_exe.ps1
```

Output executable:

- `dist/LeafPilot.exe`

## Notes

- Do not use `pip install .\requirements.txt`; use `pip install -r requirements.txt` instead.
- Close any other Chrome windows that use the same profile folder before running the script.
