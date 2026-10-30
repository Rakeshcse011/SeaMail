
import base64
import html
import json
import mimetypes
import os
import queue
import re
import threading
from datetime import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

import customtkinter as ctk
from tkinter import TclError, filedialog, messagebox

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ============================================================
# SEAMAIL - Gmail Desktop Client
# Windows 11 | Python | Gmail API
# ============================================================

APP_NAME = "SeaMail"
FONT_FAMILY = "Segoe UI"
BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
DATA_DIR = BASE_DIR / "seamail_data"
TOKEN_DIR = DATA_DIR / "tokens"

# Gmail modify permits reading and managing mail.
# Gmail send permits sending messages.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

DATA_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_DIR.mkdir(parents=True, exist_ok=True)

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

COLORS = {
    "canvas": ("#F3F6FB", "#101827"),
    "sidebar": ("#FFFFFF", "#151F30"),
    "surface": ("#FFFFFF", "#1B2738"),
    "reader_body": ("#FBFCFF", "#111C2B"),
    "credit_card": ("#EEF2FF", "#1E3154"),
    "credit_text": ("#354A76", "#B9C9EA"),
    "surface_hover": ("#EAF1FC", "#26364D"),
    "selected": ("#E8EEFF", "#25395F"),
    "selected_active": ("#D7E4FF", "#30466F"),
    "selected_border": ("#4667D5", "#89A4FF"),
    "accent": ("#3157D5", "#7695FF"),
    "accent_hover": ("#2547B8", "#5C7FE8"),
    "text": ("#101828", "#F1F5FC"),
    "muted": ("#46546A", "#C0CBD9"),
    "border": ("#E1E7F0", "#2B394D"),
}


FOLDERS = [
    ("Inbox", "INBOX"),
    ("Starred", "STARRED"),
    ("Sent", "SENT"),
    ("Drafts", "DRAFT"),
    ("Spam", "SPAM"),
    ("Trash", "TRASH"),
    ("All Mail", "ALL"),
]


def decode_body(data):
    """Decode Gmail API base64url content safely."""
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_message_parts(payload):
    """Extract readable plain-text and HTML body content."""
    plain_parts = []
    html_parts = []

    def walk(part):
        mime = part.get("mimeType", "")
        body = part.get("body") or {}
        data = body.get("data")

        if data and mime == "text/plain":
            plain_parts.append(decode_body(data))
        elif data and mime == "text/html":
            html_parts.append(decode_body(data))

        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload or {})

    if plain_parts:
        return "\n\n".join(plain_parts)
    if html_parts:
        html_source = "\n".join(html_parts)
        html_source = re.sub(
            r"(?is)<(script|style)\b.*?>.*?</\1\s*>", " ", html_source
        )
        html_source = re.sub(
            r"(?i)<br\s*/?>|</p\s*>|</div\s*>|</li\s*>",
            "\n",
            html_source,
        )
        html_source = re.sub(r"<[^>]+>", " ", html_source)
        html_source = html.unescape(html_source)
        html_source = re.sub(r"[ \t]*\n[ \t]*", "\n", html_source)
        html_source = re.sub(r"[ \t]{2,}", " ", html_source)
        html_source = re.sub(r"\n{3,}", "\n\n", html_source)
        return html_source.strip()
    return "(No readable message body.)"


def extract_attachments(payload):
    """Collect named file attachments from a Gmail message payload."""
    attachments = []

    def walk(part):
        body = part.get("body") or {}
        filename = Path(part.get("filename") or "").name
        attachment_id = body.get("attachmentId")
        data = body.get("data")
        if filename and (attachment_id or "data" in body):
            attachments.append({
                "filename": filename,
                "mime_type": part.get("mimeType", "application/octet-stream"),
                "size": body.get("size", 0),
                "attachment_id": attachment_id,
                "data": data,
                "part_id": part.get("partId", ""),
            })

        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload or {})
    return attachments


def header_value(headers, name):
    for item in headers or []:
        if item.get("name", "").lower() == name.lower():
            return item.get("value", "")
    return ""


def error_text(exc):
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", "?")
        try:
            response = json.loads(exc.content.decode("utf-8", errors="replace"))
            if isinstance(response, dict):
                detail = response.get("error", {}).get("message", str(exc))
            else:
                detail = str(exc)
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = str(exc)
        return f"Gmail API error ({status}): {detail}"
    return f"{type(exc).__name__}: {exc}"


class SeaMailApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("SeaMail | Gmail Desktop")
        self.geometry("1380x860")
        self.minsize(1050, 680)
        self.configure(fg_color=COLORS["canvas"])

        self.service = None
        self.account_email = "Not connected"
        self.current_folder = "INBOX"
        self.current_query = ""
        self.messages = []
        self.selected_message_id = None
        self.message_cards = {}
        self.busy = False
        self.auth_in_progress = False
        self.active_activities = {}
        self.events = queue.Queue()
        self._gmail_lock = threading.Lock()
        self._closing = False

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.set_status("Looking for an existing Gmail login...")
        self.after(100, self.process_events)
        self.after(300, self.connect_existing_or_sign_in)

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, minsize=236)
        self.grid_columnconfigure(1, weight=1)

        self.sidebar = ctk.CTkFrame(
            self, width=236, corner_radius=0, fg_color=COLORS["sidebar"]
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.sidebar,
            text="✉  SeaMail",
            text_color=COLORS["accent"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=27, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(24, 4), sticky="w")

        ctk.CTkLabel(
            self.sidebar,
            text="A calmer place for your inbox",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).grid(row=1, column=0, padx=20, pady=(0, 22), sticky="w")

        self.compose_button = ctk.CTkButton(
            self.sidebar,
            text="＋  Compose email",
            height=44,
            corner_radius=10,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=self.compose_email,
        )
        self.compose_button.grid(
            row=2, column=0, padx=14, pady=(0, 18), sticky="ew"
        )

        self.folder_buttons = {}
        for row, (label, folder_id) in enumerate(FOLDERS, start=3):
            button = ctk.CTkButton(
                self.sidebar,
                text=f"   {label}",
                anchor="w",
                height=39,
                corner_radius=9,
                fg_color="transparent",
                text_color=COLORS["text"],
                hover_color=COLORS["surface_hover"],
                font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                command=lambda f=folder_id: self.open_folder(f),
            )
            button.grid(row=row, column=0, padx=9, pady=2, sticky="ew")
            self.folder_buttons[folder_id] = button
        self.folder_buttons["INBOX"].configure(
            fg_color=COLORS["selected"],
            text_color=COLORS["accent"],
        )

        ctk.CTkFrame(
            self.sidebar, height=1, fg_color=COLORS["border"]
        ).grid(
            row=10, column=0, padx=15, pady=14, sticky="ew"
        )

        self.account_label = ctk.CTkLabel(
            self.sidebar,
            text="GMAIL ACCOUNT\nNot connected",
            wraplength=195,
            justify="left",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        )
        self.account_label.grid(
            row=11, column=0, padx=16, pady=(7, 10), sticky="w"
        )

        self.connect_button = ctk.CTkButton(
            self.sidebar,
            text="Connect Gmail",
            height=36,
            corner_radius=9,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self.connect_gmail,
        )
        self.connect_button.grid(
            row=12, column=0, padx=12, pady=6, sticky="ew"
        )
        ctk.CTkButton(
            self.sidebar,
            text="↻  Refresh messages",
            height=36,
            corner_radius=9,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            hover_color=COLORS["surface_hover"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            command=self.refresh_messages,
        ).grid(row=13, column=0, padx=12, pady=5, sticky="ew")
        ctk.CTkButton(
            self.sidebar,
            text="Add another account",
            height=32,
            fg_color="transparent",
            text_color=COLORS["muted"],
            hover_color=COLORS["surface_hover"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=self.add_gmail_account,
        ).grid(row=14, column=0, padx=12, pady=(2, 8), sticky="ew")

        self.sidebar.grid_rowconfigure(15, weight=1)
        credit_card = ctk.CTkFrame(
            self.sidebar,
            corner_radius=12,
            fg_color=COLORS["credit_card"],
            border_width=1,
            border_color=COLORS["accent"],
        )
        credit_card.grid(row=16, column=0, padx=12, pady=(8, 16), sticky="sew")
        credit_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            credit_card,
            text="DESIGNED & DEVELOPED BY",
            anchor="w",
            text_color=COLORS["accent"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(11, 3), sticky="ew")
        ctk.CTkLabel(
            credit_card,
            text="Rakesh Kumar Prajapati",
            anchor="w",
            text_color=COLORS["text"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        ).grid(row=1, column=0, padx=12, pady=(0, 5), sticky="ew")
        ctk.CTkLabel(
            credit_card,
            text=(
                "M. Tech (IS) · B. Tech (CSE)\n"
                "Software Professional & Trainer\n"
                "15+ Years’ Industrial Experience\n\n"
                "EMAIL\n"
                "rakeshcse011@gmail.com\n"
                "CALL / WHATSAPP\n"
                "+91-9818463305\n"
                "INSTAGRAM\n"
                "Rakesh.digital.ai"
            ),
            justify="left",
            anchor="w",
            wraplength=180,
            text_color=COLORS["credit_text"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=9),
        ).grid(row=2, column=0, padx=12, pady=(0, 11), sticky="ew")

        # Main area
        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew", padx=24, pady=20)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(3, weight=1)

        # Top toolbar
        toolbar = ctk.CTkFrame(self.main, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 22))
        toolbar.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(
            toolbar,
            placeholder_text="Search Gmail: sender, subject, keywords...",
            height=42,
            corner_radius=10,
            border_color=COLORS["border"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<Return>", lambda *_: self.search_mail())

        ctk.CTkButton(
            toolbar,
            text="Search",
            width=96,
            height=42,
            corner_radius=10,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=self.search_mail,
        ).grid(row=0, column=1, padx=(0, 8))

        ctk.CTkOptionMenu(
            toolbar,
            values=["System", "Light", "Dark"],
            width=112,
            height=42,
            corner_radius=10,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            command=self.change_theme,
        ).grid(row=0, column=2)

        self.page_title = ctk.CTkLabel(
            self.main,
            text="Inbox",
            text_color=COLORS["text"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=27, weight="bold"),
        )
        self.page_title.grid(row=1, column=0, sticky="w")
        dashboard_stats = ctk.CTkFrame(
            self.main, fg_color="transparent"
        )
        dashboard_stats.grid(
            row=2, column=0, sticky="ew", pady=(8, 14)
        )
        dashboard_stats.grid_columnconfigure(
            (0, 1, 2), weight=1, uniform="dashboard-stat"
        )
        self.dashboard_total = self._create_stat_card(
            dashboard_stats, 0, "MESSAGES IN VIEW", "0", "#3157D5"
        )
        self.dashboard_unread = self._create_stat_card(
            dashboard_stats, 1, "UNREAD", "0", "#8B5CF6"
        )
        self.dashboard_folder = self._create_stat_card(
            dashboard_stats, 2, "CURRENT FOLDER", "Inbox", "#0F9F9A"
        )

        # Split panel: message list + reader
        content = ctk.CTkFrame(
            self.main,
            corner_radius=14,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
        )
        content.grid(row=3, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=35, uniform="mail-panels")
        content.grid_columnconfigure(1, weight=65, uniform="mail-panels")
        content.grid_rowconfigure(0, weight=1)

        self.message_list = ctk.CTkScrollableFrame(
            content,
            label_text="YOUR MESSAGES",
            label_font=ctk.CTkFont(
                family=FONT_FAMILY, size=11, weight="bold"
            ),
            label_text_color=COLORS["muted"],
            fg_color="transparent",
        )
        self.message_list.grid(
            row=0, column=0, sticky="nsew", padx=(10, 4), pady=10
        )

        self.reader = ctk.CTkFrame(
            content,
            corner_radius=12,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self.reader.grid(
            row=0, column=1, sticky="nsew", padx=(4, 10), pady=10
        )
        self.reader.grid_columnconfigure(0, weight=1)
        self.reader.grid_rowconfigure(3, weight=1)

        self.reader_kicker = ctk.CTkLabel(
            self.reader,
            text="MESSAGE PREVIEW",
            text_color=COLORS["accent"],
            anchor="w",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
        )
        self.reader_kicker.grid(
            row=0, column=0, padx=18, pady=(12, 3), sticky="ew"
        )

        self.reader_subject = ctk.CTkLabel(
            self.reader,
            text="Select an email to read",
            text_color=COLORS["text"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
            anchor="w",
            wraplength=850,
            justify="left",
        )
        self.reader_subject.grid(
            row=1, column=0, padx=18, pady=(0, 5), sticky="ew"
        )

        self.reader_meta = ctk.CTkLabel(
            self.reader,
            text="Sender and date will appear here.",
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=850,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        )
        self.reader_meta.grid(
            row=2, column=0, padx=18, pady=(0, 8), sticky="ew"
        )

        self.reader_body = ctk.CTkTextbox(
            self.reader,
            wrap="word",
            corner_radius=10,
            border_width=1,
            border_color=COLORS["border"],
            fg_color=COLORS["reader_body"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=15),
            activate_scrollbars=True,
        )
        self.reader_body.grid(
            row=3, column=0, padx=12, pady=(0, 12), sticky="nsew"
        )
        self.reader_body.insert(
            "1.0",
            "Welcome to SeaMail.\n\n"
            "Connect your Gmail account to see your messages here.",
        )
        self.reader_body.configure(state="disabled")

        self.attachment_panel = ctk.CTkFrame(
            self.reader,
            corner_radius=9,
            fg_color=COLORS["selected"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self.attachment_panel.grid(
            row=4, column=0, padx=12, pady=(0, 12), sticky="ew"
        )
        self.attachment_panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.attachment_panel,
            text="ATTACHMENTS",
            anchor="w",
            text_color=COLORS["accent"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
        ).grid(row=0, column=0, padx=10, pady=(7, 3), sticky="ew")
        self.attachment_list = ctk.CTkScrollableFrame(
            self.attachment_panel,
            height=82,
            fg_color="transparent",
        )
        self.attachment_list.grid(
            row=1, column=0, padx=5, pady=(0, 5), sticky="ew"
        )
        self.attachment_panel.grid_remove()

        # Bottom status bar
        status_bar = ctk.CTkFrame(self.main, fg_color="transparent")
        status_bar.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        status_bar.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(
            status_bar,
            text="Ready",
            anchor="w",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        )
        self.status.grid(row=0, column=0, sticky="ew")
        self.activity_bar = ctk.CTkProgressBar(
            status_bar,
            width=150,
            height=5,
            corner_radius=3,
            mode="indeterminate",
            indeterminate_speed=1.5,
            progress_color=COLORS["accent"],
        )
        self.activity_bar.grid(row=0, column=1, padx=(12, 2), sticky="e")
        self.activity_bar.grid_remove()

    def _create_stat_card(self, parent, column, label, value, accent):
        card = ctk.CTkFrame(
            parent,
            corner_radius=10,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
        )
        card.grid(
            row=0,
            column=column,
            padx=(0 if column == 0 else 6, 6 if column < 2 else 0),
            sticky="ew",
        )
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card,
            text=label,
            anchor="w",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
        ).grid(row=0, column=0, padx=11, pady=(7, 0), sticky="ew")
        value_label = ctk.CTkLabel(
            card,
            text=value,
            anchor="w",
            text_color=(accent, accent),
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
        )
        value_label.grid(row=1, column=0, padx=11, pady=(0, 7), sticky="ew")
        return value_label

    def change_theme(self, choice):
        ctk.set_appearance_mode(choice)

    def set_status(self, text):
        self.status.configure(text=text)

    def _start_activity(self, key, message):
        was_idle = not self.active_activities
        count, _ = self.active_activities.get(key, (0, message))
        self.active_activities[key] = (count + 1, message)
        self.status.configure(text=message)
        if was_idle:
            self.activity_bar.grid()
            self.activity_bar.start()

    def _finish_activity(self, key):
        activity = self.active_activities.get(key)
        if activity:
            count, message = activity
            if count > 1:
                self.active_activities[key] = (count - 1, message)
            else:
                del self.active_activities[key]

        if self.active_activities:
            latest_message = list(self.active_activities.values())[-1][1]
            self.status.configure(text=latest_message)
        else:
            self.activity_bar.stop()
            self.activity_bar.grid_remove()

    def close(self):
        if self._closing:
            return

        self._closing = True
        widgets = [self]
        for widget in widgets:
            widgets.extend(widget.winfo_children())

        callback_owners = {
            command: widget
            for widget in widgets
            for command in getattr(widget, "_tclCommands", None) or []
        }
        for callback_id in self.after_info():
            try:
                command = self.after_info(callback_id)[0]
            except TclError:
                continue
            owner = callback_owners.get(command)
            if owner is not None:
                owner.after_cancel(callback_id)

        self.destroy()

    def _start_worker(self, target, args=()):
        thread = threading.Thread(
            target=target,
            args=args,
            name=f"SeaMail-{target.__name__}",
            daemon=False,
        )
        thread.start()

    def process_events(self):
        if self._closing:
            return

        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break

            kind = event[0]
            if kind == "connected":
                self._finish_activity("auth")
                self.auth_in_progress = False
                self.service, self.account_email = event[1], event[2]
                self.account_label.configure(
                    text=f"GMAIL ACCOUNT\n{self.account_email}"
                )
                if not self.active_activities:
                    self.set_status(f"Connected: {self.account_email}")
                self.refresh_messages()
            elif kind == "messages":
                self._finish_activity("messages")
                self.busy = False
                self._render_messages(event[1])
                if not self.active_activities:
                    self.set_status(f"Loaded {len(event[1])} message(s).")
            elif kind == "reader":
                self._finish_activity("reader")
                if event[1] == self.selected_message_id:
                    self._render_reader(*event[2:])
                    if not self.active_activities:
                        self.set_status("Message opened.")
            elif kind == "attachment_saved":
                self._finish_activity(event[1])
                self.set_status(f"Saved attachment: {Path(event[2]).name}")
                if event[3]:
                    try:
                        os.startfile(str(event[2]))
                    except OSError as exc:
                        messagebox.showerror(
                            "Could not open attachment",
                            f"The file was saved, but Windows could not open it:\n{exc}",
                        )
            elif kind == "attachment_error":
                self._finish_activity(event[1])
                self.set_status(event[2])
                messagebox.showerror("Attachment download failed", event[2])
            elif kind == "load_error":
                self._finish_activity("messages")
                self.busy = False
                self.set_status(event[1])
                messagebox.showerror(event[2], event[1])
            elif kind == "error":
                activity = event[3] if len(event) > 3 else "auth"
                self._finish_activity(activity)
                if activity == "auth":
                    self.auth_in_progress = False
                self.set_status(event[1])
                messagebox.showerror(event[2], event[1])
            elif kind == "no_saved_login":
                self._finish_activity("auth")
                self.auth_in_progress = False
                self.set_status(event[1])
            elif kind == "sent":
                self._finish_activity("send")
                self.set_status("Email sent successfully.")
                messagebox.showinfo("SeaMail", "Email sent successfully.")
                self.refresh_messages()

        if not self._closing:
            self.after(100, self.process_events)

    # --------------------------------------------------------
    # Authentication - reuse saved tokens where possible
    # --------------------------------------------------------

    def _token_files(self):
        token_files = list(TOKEN_DIR.glob("*.json"))
        legacy_token = BASE_DIR / "token.json"
        if legacy_token.is_file():
            token_files.append(legacy_token)
        return sorted(
            token_files,
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def _service_from_token(self, token_path):
        creds = Credentials.from_authorized_user_file(
            str(token_path), SCOPES
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")

        if not creds.valid:
            raise RuntimeError("Saved Gmail login is expired or invalid.")

        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def connect_existing_or_sign_in(self):
        if self.auth_in_progress:
            return
        self.auth_in_progress = True
        self._start_activity("auth", "Checking saved Gmail accounts…")
        self._start_worker(self._connect_existing_worker)

    def connect_gmail(self):
        if self.service is not None:
            self.set_status(f"Already connected: {self.account_email}")
            self.refresh_messages()
            return
        if self.auth_in_progress:
            self.set_status("Gmail connection is already in progress...")
            return

        self.auth_in_progress = True
        self._start_activity("auth", "Checking saved Gmail login…")
        self._start_worker(self._connect_or_oauth_worker)

    def _connect_existing_worker(self):
        failures = []
        for token_path in self._token_files():
            try:
                service = self._service_from_token(token_path)
                profile = service.users().getProfile(userId="me").execute()
                self.events.put((
                    "connected",
                    service,
                    profile.get("emailAddress", "Gmail account"),
                ))
                return
            except Exception as exc:
                failures.append(f"{token_path.name}: {error_text(exc)}")

        status = "No usable saved login found. Click Connect Gmail to continue."
        if failures:
            status += f" {len(failures)} saved login(s) could not be used."
        self.events.put((
            "no_saved_login",
            status,
        ))

    def _connect_or_oauth_worker(self):
        failures = []
        for token_path in self._token_files():
            try:
                service = self._service_from_token(token_path)
                profile = service.users().getProfile(userId="me").execute()
                self.events.put((
                    "connected",
                    service,
                    profile.get("emailAddress", "Gmail account"),
                ))
                return
            except Exception as exc:
                failures.append(f"{token_path.name}: {error_text(exc)}")

        self._oauth_worker(failures)

    def add_gmail_account(self):
        if self.auth_in_progress:
            self.set_status("Gmail connection is already in progress...")
            return

        self.auth_in_progress = True
        self._start_activity("auth", "Opening Google sign-in…")
        self._start_worker(self._oauth_worker)

    def _oauth_worker(self, saved_token_failures=()):
        try:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Place your valid Google OAuth Desktop app file here:\n"
                    f"{CREDENTIALS_FILE}"
                )

            data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            if "installed" not in data and "web" not in data:
                raise ValueError(
                    "Expected an OAuth client JSON with 'installed' or 'web'."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(
                port=0,
                open_browser=True,
                timeout_seconds=120,
            )

            service = build(
                "gmail",
                "v1",
                credentials=creds,
                cache_discovery=False,
            )
            profile = service.users().getProfile(userId="me").execute()

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            token_path = TOKEN_DIR / f"account_{stamp}.json"
            token_path.write_text(creds.to_json(), encoding="utf-8")

            self.events.put((
                "connected",
                service,
                profile.get("emailAddress", "Gmail account"),
            ))
        except Exception as exc:
            details = ""
            if saved_token_failures:
                details = "\n\nSaved login attempts:\n" + "\n".join(
                    saved_token_failures[:3]
                )
            self.events.put((
                "error",
                f"Gmail connection failed: {error_text(exc)}{details}",
                "Gmail connection failed",
                "auth",
            ))

    # --------------------------------------------------------
    # Folders and search
    # --------------------------------------------------------

    def open_folder(self, folder_id):
        self.current_folder = folder_id
        self.current_query = ""
        self.search_entry.delete(0, "end")

        for current_id, button in self.folder_buttons.items():
            active = current_id == folder_id
            button.configure(
                fg_color=COLORS["selected"] if active else "transparent",
                text_color=COLORS["accent"] if active else COLORS["text"],
            )

        folder_name = next(
            (name for name, fid in FOLDERS if fid == folder_id),
            "Inbox",
        )
        self.page_title.configure(text=folder_name)
        self.dashboard_folder.configure(text=folder_name)
        self.refresh_messages()

    def search_mail(self):
        self.current_query = self.search_entry.get().strip()
        self.page_title.configure(
            text=f'Search: {self.current_query or "All messages"}'
        )
        self.refresh_messages()

    def refresh_messages(self):
        if not self.service:
            self.set_status("Connect Gmail first.")
            return
        if self.busy:
            self.set_status("A request is already running. Please wait.")
            return

        self.busy = True
        self._start_activity("messages", "Loading messages…")
        service = self.service
        folder = self.current_folder
        query = self.current_query
        self._start_worker(
            self._load_messages_worker,
            args=(service, folder, query),
        )

    def _load_messages_worker(self, service, folder, query):
        try:
            params = {
                "userId": "me",
                "maxResults": 50,
            }

            if folder == "ALL":
                params["q"] = " ".join(
                    part for part in ("in:anywhere", query) if part
                )
            else:
                params["labelIds"] = [folder]
                if query:
                    params["q"] = query

            results = []
            with self._gmail_lock:
                response = service.users().messages().list(**params).execute()
                ids = response.get("messages", [])
                message_service = service.users().messages()
                metadata_by_index = {}
                if ids:
                    batch = service.new_batch_http_request()

                    def collect_metadata(request_id, result, exception):
                        metadata_by_index[request_id] = (result, exception)

                    for index, item in enumerate(ids):
                        request = message_service.get(
                            userId="me",
                            id=item["id"],
                            format="metadata",
                            metadataHeaders=["From", "Subject", "Date"],
                        )
                        batch.add(
                            request,
                            request_id=str(index),
                            callback=collect_metadata,
                        )
                    batch.execute()

                for index, item in enumerate(ids):
                    msg, exception = metadata_by_index.get(
                        str(index),
                        (None, RuntimeError("Gmail returned no message metadata.")),
                    )
                    if exception:
                        results.append({
                            "id": item.get("id", ""),
                            "threadId": "",
                            "from": "(Metadata unavailable)",
                            "subject": "(Could not load message metadata)",
                            "date": "",
                            "snippet": error_text(exception),
                            "labels": [],
                        })
                        continue

                    headers = msg.get("payload", {}).get("headers", [])
                    results.append({
                        "id": msg["id"],
                        "threadId": msg.get("threadId", ""),
                        "from": header_value(headers, "From") or "(Unknown sender)",
                        "subject": header_value(headers, "Subject") or "(No subject)",
                        "date": header_value(headers, "Date"),
                        "snippet": msg.get("snippet", ""),
                        "labels": msg.get("labelIds", []),
                    })

            self.events.put(("messages", results))

        except Exception as exc:
            self.events.put((
                "load_error",
                f"Could not load messages: {error_text(exc)}",
                "Gmail loading",
            ))

    def _render_messages(self, results):
        self.messages = results
        self.message_cards.clear()

        for child in self.message_list.winfo_children():
            child.destroy()

        if not results:
            self.dashboard_total.configure(text="0")
            self.dashboard_unread.configure(text="0")
            ctk.CTkLabel(
                self.message_list,
                text="No messages found.",
                text_color=("gray40", "gray70"),
            ).pack(padx=10, pady=20)
            return

        unread_count = sum(
            "UNREAD" in msg.get("labels", []) for msg in results
        )
        self.dashboard_total.configure(text=str(len(results)))
        self.dashboard_unread.configure(text=str(unread_count))

        for msg in results:
            unread = "UNREAD  ·  " if "UNREAD" in msg["labels"] else ""
            is_unread = "UNREAD" in msg["labels"]
            is_selected = msg["id"] == self.selected_message_id
            snippet = msg.get("snippet", "").strip()
            if len(snippet) > 105:
                snippet = snippet[:102].rstrip() + "…"
            card_color = self._message_card_color(is_selected, is_unread)
            card = ctk.CTkFrame(
                self.message_list,
                height=88,
                corner_radius=9,
                fg_color=card_color,
                border_width=2 if is_selected else 0,
                border_color=COLORS["selected_border"],
            )
            card.pack(fill="x", padx=5, pady=4)
            card.grid_columnconfigure(0, weight=1)
            self.message_cards[msg["id"]] = {
                "frame": card,
                "unread": is_unread,
            }
            sender_label = ctk.CTkLabel(
                card,
                text=f"{unread}{msg['from']}",
                anchor="w",
                text_color=COLORS["accent"] if is_unread else COLORS["text"],
                font=ctk.CTkFont(
                    family=FONT_FAMILY,
                    size=12,
                    weight="bold" if is_unread else "normal",
                ),
            )
            sender_label.grid(
                row=0, column=0, padx=11, pady=(8, 0), sticky="ew"
            )
            subject_label = ctk.CTkLabel(
                card,
                text=msg["subject"],
                anchor="w",
                text_color=COLORS["text"],
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            )
            subject_label.grid(
                row=1, column=0, padx=11, pady=(1, 0), sticky="ew"
            )
            snippet_label = ctk.CTkLabel(
                card,
                text=snippet or " ",
                anchor="w",
                text_color=COLORS["muted"],
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            )
            snippet_label.grid(
                row=2, column=0, padx=11, pady=(1, 8), sticky="ew"
            )

            def open_selected(_event, message_id=msg["id"]):
                self.open_message(message_id)

            def set_card_hover(_event, frame=card):
                frame.configure(fg_color=COLORS["surface_hover"])

            def clear_card_hover(
                _event,
                frame=card,
                message_id=msg["id"],
                unread_flag=is_unread,
            ):
                selected = self.selected_message_id == message_id
                frame.configure(
                    fg_color=self._message_card_color(selected, unread_flag),
                    border_width=2 if selected else 0,
                    border_color=COLORS["selected_border"],
                )

            for widget in (card, sender_label, subject_label, snippet_label):
                widget.bind("<Button-1>", open_selected)
                widget.bind("<Enter>", set_card_hover)
                widget.bind("<Leave>", clear_card_hover)

    def _message_card_color(self, selected, unread):
        if selected:
            return COLORS["selected_active"]
        if unread:
            return COLORS["selected"]
        return COLORS["reader_body"]

    def _refresh_selected_message_card(self):
        for message_id, widgets in self.message_cards.items():
            selected = message_id == self.selected_message_id
            widgets["frame"].configure(
                fg_color=self._message_card_color(
                    selected, widgets["unread"]
                ),
                border_width=2 if selected else 0,
                border_color=COLORS["selected_border"],
            )

    # --------------------------------------------------------
    # Read a message
    # --------------------------------------------------------

    def open_message(self, message_id):
        if not self.service or not message_id:
            return

        self.selected_message_id = message_id
        self._refresh_selected_message_card()
        self._start_activity("reader", "Opening message…")
        service = self.service
        self._start_worker(
            self._open_message_worker,
            args=(service, message_id),
        )

    def _open_message_worker(self, service, message_id):
        try:
            with self._gmail_lock:
                msg = service.users().messages().get(
                    userId="me",
                    id=message_id,
                    format="full",
                ).execute()

            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            subject = header_value(headers, "Subject") or "(No subject)"
            sender = header_value(headers, "From") or "(Unknown sender)"
            date = header_value(headers, "Date")
            body = extract_message_parts(payload)
            attachments = extract_attachments(payload)

            try:
                if date:
                    date = parsedate_to_datetime(date).astimezone().strftime(
                        "%d %b %Y, %I:%M %p"
                    )
            except Exception:
                pass

            self.events.put((
                "reader",
                message_id,
                subject,
                sender,
                date,
                body,
                attachments,
            ))

        except Exception as exc:
            self.events.put((
                "error",
                f"Could not open message: {error_text(exc)}",
                "Message reader",
                "reader",
            ))

    def _render_reader(self, subject, sender, date, body, attachments=()):
        self.reader_subject.configure(text=subject)
        self.reader_meta.configure(text=f"From  {sender}\nReceived  {date}")

        self.reader_body.configure(state="normal")
        self.reader_body.delete("1.0", "end")
        self.reader_body.insert("1.0", body)
        self.reader_body.configure(state="disabled")

        for child in self.attachment_list.winfo_children():
            child.destroy()

        if not attachments:
            self.attachment_panel.grid_remove()
            return

        self.attachment_panel.grid()
        self.reader.winfo_toplevel().update_idletasks()
        self.reader_body.configure(
            height=max(8, self.reader.winfo_height() // 28 - 7)
        )
        self.attachment_panel.winfo_children()[0].configure(
            text=f"ATTACHMENTS  ·  {len(attachments)}"
        )

        for row, attachment in enumerate(attachments):
            item = ctk.CTkFrame(
                self.attachment_list,
                corner_radius=8,
                fg_color=COLORS["reader_body"],
            )
            item.grid(row=row, column=0, padx=3, pady=3, sticky="ew")
            item.grid_columnconfigure(0, weight=1)

            size = attachment.get("size", 0)
            size_text = (
                f"{size / 1024:.1f} KB" if size else attachment["mime_type"]
            )
            ctk.CTkLabel(
                item,
                text=f"📎  {attachment['filename']}   ·   {size_text}",
                anchor="w",
                text_color=COLORS["text"],
                font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            ).grid(row=0, column=0, padx=9, pady=6, sticky="ew")

            attachment_key = (
                f"attachment:{self.selected_message_id}:{row}"
            )
            ctk.CTkButton(
                item,
                text="Save",
                width=62,
                height=28,
                corner_radius=7,
                font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                command=lambda file=attachment, key=attachment_key: (
                    self._save_attachment(file, key, open_after=False)
                ),
            ).grid(row=0, column=1, padx=(4, 3), pady=4)
            ctk.CTkButton(
                item,
                text="Open",
                width=62,
                height=28,
                corner_radius=7,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS["accent"],
                text_color=COLORS["accent"],
                hover_color=COLORS["surface_hover"],
                font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                command=lambda file=attachment, key=attachment_key: (
                    self._save_attachment(file, key, open_after=True)
                ),
            ).grid(row=0, column=2, padx=(0, 5), pady=4)

    def _save_attachment(self, attachment, activity_key, open_after):
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Save email attachment",
            initialfile=Path(attachment["filename"]).name,
            filetypes=[("All files", "*.*")],
        )
        if not destination:
            return

        self._start_activity(
            activity_key,
            f"Downloading {Path(destination).name}…",
        )
        self._start_worker(
            self._download_attachment_worker,
            args=(
                self.service,
                self.selected_message_id,
                attachment,
                destination,
                activity_key,
                open_after,
            ),
        )

    def _download_attachment_worker(
        self, service, message_id, attachment, destination, activity_key, open_after
    ):
        try:
            data = attachment.get("data")
            if data is None:
                attachment_id = attachment.get("attachment_id")
                if not attachment_id:
                    raise ValueError("This attachment has no downloadable data.")
                with self._gmail_lock:
                    response = (
                        service.users()
                        .messages()
                        .attachments()
                        .get(
                            userId="me",
                            messageId=message_id,
                            id=attachment_id,
                        )
                        .execute()
                    )
                if "data" not in response:
                    raise ValueError("Gmail returned no attachment data.")
                data = response["data"]

            content = base64.urlsafe_b64decode(
                data + "=" * (-len(data) % 4)
            )
            Path(destination).write_bytes(content)
            self.events.put((
                "attachment_saved",
                activity_key,
                destination,
                open_after,
            ))
        except Exception as exc:
            self.events.put((
                "attachment_error",
                activity_key,
                f"Could not save {attachment['filename']}: {error_text(exc)}",
            ))

    def _compose_html(self, text_widget):
        body = text_widget.get("1.0", "end-1c")
        style_order = ("heading", "subheading", "quote", "bold", "italic", "underline")
        wrappers = {
            "heading": (
                '<span style="font-size:24px;font-weight:700;color:#3157d5">',
                "</span>",
            ),
            "subheading": (
                '<span style="font-size:18px;font-weight:600;color:#263a63">',
                "</span>",
            ),
            "quote": (
                '<span style="color:#66738a;font-style:italic;'
                'border-left:3px solid #9aabc7;padding-left:10px">',
                "</span>",
            ),
            "bold": ("<strong>", "</strong>"),
            "italic": ("<em>", "</em>"),
            "underline": ("<u>", "</u>"),
        }

        html_parts = []
        run_text = []
        run_styles = ()

        def append_run():
            if not run_text:
                return
            escaped = html.escape("".join(run_text))
            for style in run_styles:
                escaped = wrappers[style][0] + escaped + wrappers[style][1]
            html_parts.append(escaped)
            run_text.clear()

        for offset, character in enumerate(body):
            if character == "\n":
                append_run()
                html_parts.append("<br>\n")
                run_styles = ()
                continue

            active_tags = set(
                text_widget._textbox.tag_names(f"1.0 + {offset} chars")
            )
            styles = tuple(
                style for style in style_order if style in active_tags
            )
            if run_text and styles != run_styles:
                append_run()
            run_styles = styles
            run_text.append(character)

        append_run()
        return (
            '<div style="font-family:Arial,sans-serif;font-size:14px;'
            'line-height:1.65;color:#263245">'
            + "".join(html_parts)
            + "</div>"
        )

    def compose_email(self):
        if not self.service:
            messagebox.showwarning(
                "Gmail not connected", "Connect your Gmail account first."
            )
            return

        window = ctk.CTkToplevel(self)
        window.title("Compose Email - SeaMail")
        window.geometry("800x760")
        window.minsize(620, 560)
        window.configure(fg_color=COLORS["canvas"])
        window.transient(self)
        window.grab_set()
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(
            window,
            text="New message",
            text_color=COLORS["text"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=24, weight="bold"),
        ).grid(row=0, column=0, padx=22, pady=(20, 12), sticky="w")

        ctk.CTkLabel(
            window,
            text="TO",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
        ).grid(row=1, column=0, padx=22, pady=(2, 4), sticky="w")
        recipient_entry = ctk.CTkEntry(
            window,
            placeholder_text="recipient@example.com (separate multiple addresses with commas)",
            height=40,
            corner_radius=9,
            border_color=COLORS["border"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        )
        recipient_entry.grid(
            row=2, column=0, padx=22, pady=(0, 10), sticky="ew"
        )

        ctk.CTkLabel(
            window,
            text="SUBJECT",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
        ).grid(
            row=3, column=0, padx=22, pady=(2, 4), sticky="w"
        )
        subject_entry = ctk.CTkEntry(
            window,
            placeholder_text="Give your message a clear subject",
            height=40,
            corner_radius=9,
            border_color=COLORS["border"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        )
        subject_entry.grid(
            row=4, column=0, padx=22, pady=(0, 10), sticky="ew"
        )

        formatting = ctk.CTkFrame(
            window,
            corner_radius=9,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
        )
        formatting.grid(row=5, column=0, padx=22, pady=(0, 8), sticky="ew")

        body = ctk.CTkTextbox(
            window,
            wrap="word",
            corner_radius=10,
            border_width=1,
            border_color=COLORS["border"],
            fg_color=COLORS["surface"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            activate_scrollbars=True,
        )
        body.grid(row=6, column=0, padx=22, pady=(0, 8), sticky="nsew")
        text_widget = body._textbox
        text_widget.tag_configure(
            "heading",
            font=(FONT_FAMILY, 24, "bold"),
            foreground="#3157D5",
            spacing1=5,
            spacing3=5,
        )
        text_widget.tag_configure(
            "subheading",
            font=(FONT_FAMILY, 18, "bold"),
            foreground="#263A63",
            spacing1=3,
            spacing3=3,
        )
        text_widget.tag_configure(
            "quote",
            font=(FONT_FAMILY, 13, "italic"),
            foreground="#66738A",
            lmargin1=16,
            lmargin2=16,
        )
        text_widget.tag_configure("bold", font=(FONT_FAMILY, 13, "bold"))
        text_widget.tag_configure("italic", font=(FONT_FAMILY, 13, "italic"))
        text_widget.tag_configure("underline", underline=True)

        def apply_inline_style(tag):
            selection = text_widget.tag_ranges("sel")
            if not selection:
                self.set_status("Select text in the message to format it.")
                return

            selected_tags = text_widget.tag_names(selection[0])
            if tag in selected_tags:
                text_widget.tag_remove(tag, *selection)
            else:
                text_widget.tag_add(tag, *selection)

        def apply_block_style(choice):
            selection = text_widget.tag_ranges("sel")
            if not selection:
                self.set_status("Select text in the message to format it.")
                return

            for tag in ("heading", "subheading", "quote"):
                text_widget.tag_remove(tag, *selection)

            style = {
                "Heading": "heading",
                "Subheading": "subheading",
                "Quote": "quote",
            }.get(choice)
            if style:
                text_widget.tag_add(style, *selection)
            text_widget.focus_set()

        for column, (label, style) in enumerate(
            (("B", "bold"), ("I", "italic"), ("U", "underline"))
        ):
            ctk.CTkButton(
                formatting,
                text=label,
                width=38,
                height=32,
                corner_radius=7,
                fg_color="transparent",
                text_color=COLORS["text"],
                hover_color=COLORS["surface_hover"],
                font=ctk.CTkFont(
                    family=FONT_FAMILY,
                    size=13,
                    weight="bold" if style == "bold" else "normal",
                    slant="italic" if style == "italic" else "roman",
                    underline=style == "underline",
                ),
                command=lambda selected_style=style: apply_inline_style(
                    selected_style
                ),
            ).grid(row=0, column=column, padx=(5 if column == 0 else 0, 0), pady=4)

        ctk.CTkLabel(
            formatting,
            text="Format selected text",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).grid(row=0, column=3, padx=(12, 6), pady=4)
        ctk.CTkOptionMenu(
            formatting,
            values=["Body", "Heading", "Subheading", "Quote"],
            width=132,
            height=32,
            corner_radius=7,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=apply_block_style,
        ).grid(row=0, column=4, padx=(0, 6), pady=4)

        body.bind(
            "<Control-b>",
            lambda *_: (apply_inline_style("bold"), "break")[1],
        )
        body.bind(
            "<Control-i>",
            lambda *_: (apply_inline_style("italic"), "break")[1],
        )
        body.bind(
            "<Control-u>",
            lambda *_: (apply_inline_style("underline"), "break")[1],
        )

        attachment_label = ctk.CTkLabel(
            window,
            text="No attachments selected",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        )
        attachment_label.grid(
            row=7, column=0, padx=22, pady=4, sticky="w"
        )
        selected_files = []

        def choose_files():
            paths = filedialog.askopenfilenames(parent=window)
            if paths:
                selected_files.extend(
                    path for path in paths if path not in selected_files
                )
                attachment_label.configure(
                    text="Attachments: "
                    + ", ".join(Path(path).name for path in selected_files)
                )

        def send():
            recipients = [
                value.strip()
                for value in recipient_entry.get().split(",")
                if value.strip()
            ]
            if not recipients:
                messagebox.showwarning(
                    "Missing recipient",
                    "Enter at least one recipient.",
                    parent=window,
                )
                return

            if not messagebox.askyesno(
                "Confirm Send",
                "Send this email now to:\n" + ", ".join(recipients) + "?",
                parent=window,
            ):
                return

            service = self.service
            message_body = body.get("1.0", "end-1c")
            html_body = self._compose_html(body)
            subject = subject_entry.get().strip()
            files = list(selected_files)
            window.destroy()
            self._start_activity("send", "Preparing and sending email…")
            self._start_worker(
                self._send_worker,
                args=(
                    service,
                    recipients,
                    subject,
                    message_body,
                    html_body,
                    files,
                ),
            )

        actions = ctk.CTkFrame(window, fg_color="transparent")
        actions.grid(row=8, column=0, padx=22, pady=(8, 18), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            actions,
            text="Attach files",
            height=38,
            corner_radius=9,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            hover_color=COLORS["surface_hover"],
            command=choose_files,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            actions,
            text="Send email",
            height=38,
            corner_radius=9,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=send,
        ).grid(row=0, column=1, padx=(8, 0), sticky="e")

    def _send_worker(self, service, recipients, subject, body, html_body, files):
        try:
            message = EmailMessage()
            message["To"] = ", ".join(recipients)
            message["Subject"] = subject or "(No subject)"
            message.set_content(body)
            message.add_alternative(html_body, subtype="html")

            for filename in files:
                path = Path(filename)
                if not path.is_file():
                    raise FileNotFoundError(f"Attachment not found: {path}")

                mime_type, _ = mimetypes.guess_type(str(path))
                maintype, subtype = (
                    mime_type.split("/", 1)
                    if mime_type
                    else ("application", "octet-stream")
                )
                message.add_attachment(
                    path.read_bytes(),
                    maintype=maintype,
                    subtype=subtype,
                    filename=path.name,
                )

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
            with self._gmail_lock:
                service.users().messages().send(
                    userId="me", body={"raw": raw}
                ).execute()
            self.events.put(("sent",))
        except Exception as exc:
            self.events.put((
                "error",
                f"Could not send email: {error_text(exc)}",
                "Send email",
                "send",
            ))


if __name__ == "__main__":
    app = SeaMailApp()
    app.mainloop()
