# SeaMail — Gmail Desktop Application

**Python • CustomTkinter • Gmail API • Windows 11**

## 1. Project Overview

SeaMail is a Python-based desktop email application designed to connect with a Gmail account using Google's Gmail API.

The application is intended to provide a desktop interface for viewing emails, searching messages, opening email content, composing messages, and sending emails.

**Project location:** `C:\Users\Aakarsh\seaMail`

**Main application:** `app2.py`

**Operating system:** Windows 11

**Python environment:** Virtual environment (`.venv`)

## 2. Features

The current application code is intended to support:

- Gmail account authentication through Google OAuth 2.0.
- Viewing Inbox messages.
- Viewing Starred, Sent, Drafts, Spam, Trash, and All Mail folders.
- Searching Gmail messages.
- Opening and reading email messages.
- Composing and sending emails.
- Adding file attachments to outgoing emails.
- Storing authentication tokens locally to reduce repeated login prompts.
- Loading email data in background threads to keep the interface responsive.

*Note: Confirm each feature in the running application before considering it fully tested.*

## 3. Project Structure

Expected project structure:

```text
seaMail/
├── app2.py
├── app2_backup.py
├── app2_error_backup.py
├── credentials.json
├── .venv/
├── seamail_data/
│   └── tokens/
└── README.md
```

Some files or directories may not exist yet. Backup filenames depend on which backup commands have been run.

### Important files

| File or folder | Purpose |
|---|---|
| `app2.py` | Main Python application |
| `.venv/` | Isolated Python environment and dependencies |
| `credentials.json` | Google OAuth client credentials |
| `seamail_data/tokens/` | Locally saved OAuth tokens |
| `README.md` | Project documentation |
| `app2_backup.py` | Optional backup of the application |

**Security:** Never upload or publicly share `credentials.json`, saved token JSON files, or other authentication secrets.

## 4. Requirements

- Windows 11
- Python installed on the computer
- PowerShell
- Internet connection
- Google account
- Google Cloud project with the Gmail API enabled
- OAuth client credentials configured for a desktop application
- Python packages listed below

## 5. Installation

Open PowerShell and navigate to the project directory:

```powershell
cd C:\Users\Aakarsh\seaMail
```

### Create a virtual environment

If `.venv` already exists, do not recreate it unnecessarily.

```powershell
python -m venv .venv
```

### Activate the environment

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell activation is blocked, you can use the environment's Python executable directly without activation.

### Install dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade customtkinter google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib
```

## 6. Google Gmail API Configuration

1. Open the Google Cloud Console: https://console.cloud.google.com/
2. Select or create a Google Cloud project.
3. Enable the Gmail API.
4. Configure the OAuth consent screen and permitted test users if required.
5. Create an OAuth client ID for a Desktop application.
6. Download the OAuth client credentials JSON file.
7. Place the file in the project directory using the filename expected by the application, normally `credentials.json`.

The application may request Gmail permissions for reading, modifying, and sending messages.

Review the requested permissions before granting access. Do not share access tokens or credentials with other people.

## 7. Run SeaMail

From PowerShell:

```powershell
cd C:\Users\Aakarsh\seaMail
```

Start the application:

```powershell
.\.venv\Scripts\python.exe app2.py
```

On the first connection, Google requires you to approve the requested Gmail
permissions in a browser. SeaMail then saves the login locally and reconnects
automatically on later runs. Click **Connect Gmail** to retry a saved login;
the browser opens only if no saved login can be used. Use **Add another
account** to authorize an additional account.

Once connected, test the email folders and other available features.

The compose window includes selection-based formatting for bold, italic,
underline, headings, subheadings, and quotes. Formatted messages are sent as
HTML with a plain-text alternative. The sidebar includes the application
designer/developer attribution. The message reader keeps a compact,
left-aligned header above a high-contrast reading area, and an animated
activity indicator appears during background Gmail and attachment operations.
Message metadata is fetched in a Gmail API batch to reduce serial network
round-trips when loading a folder.
Received file attachments appear beneath the message body with **Save** and
**Open** actions. Outgoing attachments are included as MIME file parts with
their detected content types; SeaMail does not send files until you confirm
the send action.

## 8. Basic Testing Checklist

Use this checklist to record actual results.

- [ ] Application opens without a Python traceback.
- [ ] Gmail OAuth authentication completes successfully.
- [ ] Inbox messages load.
- [ ] Email subject buttons appear in the message list.
- [ ] Selecting a message opens its contents.
- [ ] Gmail search returns expected messages.
- [ ] Folder navigation works.
- [ ] Compose window opens.
- [ ] A test email can be sent to an account you control.
- [ ] An attachment can be sent and received.
- [ ] Closing and reopening the app does not cause unnecessary repeated authorization.

Do not mark a test as successful until it has been performed.

## 9. Troubleshooting

### A. `CTkButton` does not support `justify`

Example error:

```text
ValueError: ['justify'] are not supported arguments
```

Cause: The application is passing an unsupported argument to a CustomTkinter button.

Check the code:

```powershell
Select-String -Path .\app2.py -Pattern 'CTkButton|justify=' -Context 2,4
```

Remove `justify=` from `CTkButton` arguments. For supported button text positioning, use `anchor="w"` where appropriate.

### B. `AttributeError: 'CTkButton' object has no attribute '_font'`

Example error:

```text
AttributeError: 'CTkButton' object has no attribute '_font'
```

This can happen when a button fails during initialization and Tkinter subsequently attempts to destroy the partially initialized widget.

The `_font` error may be a secondary exception. Identify the **first exception in the traceback**, especially the code that originally creates the button.

Recommended debugging steps:

1. Stop the application.
2. Back up `app2.py`.
3. Inspect the original button-construction error.
4. Check all arguments passed to `CTkButton`.
5. Update CustomTkinter if needed.
6. Correct the original initialization failure.
7. Test folder navigation and message-list refresh again.

Avoid relying only on `try/except` around `destroy()`. Suppressing the cleanup error does not repair the original widget initialization problem.

### C. Update CustomTkinter

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade customtkinter
```

### D. Check Python syntax

```powershell
.\.venv\Scripts\python.exe -m py_compile .\app2.py
```

No output generally indicates that the file passed the syntax check. Runtime errors can still occur.

### E. Capture the application traceback

Run:

```powershell
.\.venv\Scripts\python.exe -u .\app2.py *> .\seamail_error.txt
```

Reproduce the error, close the application, and inspect the captured output:

```powershell
Get-Content .\seamail_error.txt -TotalCount 100
```

Share the first relevant exception and surrounding traceback when requesting debugging help.

### F. Gmail authorization repeats

Check whether valid token files are saved in:

```text
seamail_data\tokens\
```

Do not delete token files as a first troubleshooting step. Repeated login prompts can result from missing, expired, invalid, or insufficiently scoped credentials, or from the application selecting an older token.

SeaMail checks its saved account tokens and the legacy project-level
`token.json` before opening Google sign-in. Google requires browser consent at
least once for each account and permission set; the app cannot bypass that
consent. After approval, the saved refresh token should allow later runs to
connect without another sign-in.

## 10. Backup and Recovery

Before changing application code:

```powershell
Copy-Item .\app2.py .\app2_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').py
```

This creates a timestamped backup of the current application file.

Keep OAuth credentials and token files protected. Back up sensitive files only to a secure location.

## 11. Development Notes

- Use the virtual environment's Python executable to ensure the expected packages are used.
- Keep Google API calls out of long-running operations on the Tkinter UI thread.
- Update UI widgets on the main thread.
- Validate widget arguments against the installed CustomTkinter version.
- Log the original exception before attempting cleanup.
- Test email loading, folder switching, message reading, sending, and authorization after every major change.

## 12. Current Known Issue

**Status: Troubleshooting required**

The application has reported repeated errors during Tkinter widget destruction:

```text
AttributeError: 'CTkButton' object has no attribute '_font'
```

The original initialization exception has not yet been conclusively identified from the supplied traceback.

The next debugging step is to inspect the current `app2.py` file and capture the earliest exception. The application should not be considered fully repaired until message-list refresh and application shutdown work without these errors.

## 13. Useful Commands Reference

| Task | Command |
|---|---|
| Open project directory | `cd C:\Users\Aakarsh\seaMail` |
| Check Python version | `.\.venv\Scripts\python.exe --version` |
| Install dependencies | `.\.venv\Scripts\python.exe -m pip install --upgrade customtkinter google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib` |
| Check syntax | `.\.venv\Scripts\python.exe -m py_compile .\app2.py` |
| Run application | `.\.venv\Scripts\python.exe app2.py` |
| Search button code | `Select-String -Path .\app2.py -Pattern 'CTkButton|justify=' -Context 2,4` |

## 14. Project Summary

SeaMail is a Gmail-connected Python desktop application using CustomTkinter for its graphical interface and Google's Gmail API for email operations.

The immediate development priority is to resolve the incomplete `CTkButton` initialization error, verify email-list rendering, and confirm that the application can close cleanly. Further enhancements should be added only after the core workflow is stable.
