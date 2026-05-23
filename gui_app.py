import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import json
import threading
import sys
import os
import traceback
from pathlib import Path
import csv
from datetime import datetime
from PIL import Image, ImageTk

# Import project modules
from config import AppConfig
from browser_manager import ChromeBrowserManager
from overleaf_automation import OverleafProjectSharer
from config import _normalize_project_url

SETTINGS_FILE = "settings.json"

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class TextHandler:
    """Redirects stdout/stderr to a Tkinter ScrolledText widget."""
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, string):
        self.text_widget.after(0, self._insert, string)

    def _insert(self, string):
        self.text_widget.configure(state='normal')
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state='disabled')

    def flush(self):
        pass

class LeafPilotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("LeafPilot - Smart Overleaf Automation")
        self.root.geometry("900x780")
        self.root.configure(bg="#ffffff")
        
        # Load App Icon
        self.set_app_icon()
        
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Define Premium Color Palette
        self.bg_color = "#ffffff"
        self.sidebar_color = "#1e293b"
        self.accent_color = "#3b82f6"
        self.header_color = "#f8fafc"
        self.text_color = "#334155"
        self.success_color = "#10b981"
        self.error_color = "#ef4444"

        self.style.configure("TFrame", background=self.bg_color)
        self.style.configure("TLabel", background=self.bg_color, foreground=self.text_color, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground=self.sidebar_color, background=self.header_color)
        self.style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        
        # Custom button styles
        self.style.configure("Action.TButton", foreground="white", background=self.accent_color)
        self.style.map("Action.TButton", background=[('active', '#2563eb'), ('disabled', '#cbd5e1')])
        
        self.style.configure("Stop.TButton", foreground="white", background=self.error_color)
        self.style.map("Stop.TButton", background=[('active', '#dc2626'), ('disabled', '#cbd5e1')])

        self.settings = self.load_settings()
        self.automation_thread = None
        self.stop_event = threading.Event()

        self.setup_ui()
        
        # Redirect stdout to the log widget
        sys.stdout = TextHandler(self.log_widget)

    def set_app_icon(self):
        try:
            icon_path = resource_path("logo.png")
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
                photo = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, photo)
                self.app_logo = photo # Keep reference
        except Exception as e:
            print(f"Warning: Could not load application icon: {e}")

    def setup_ui(self):
        # Header Area
        header_frame = tk.Frame(self.root, bg=self.header_color, height=80, highlightthickness=1, highlightbackground="#e2e8f0")
        header_frame.pack(fill=tk.X, side=tk.TOP)
        header_frame.pack_propagate(False)
        
        # Title Container
        title_container = tk.Frame(header_frame, bg=self.header_color)
        title_container.pack(side=tk.LEFT, padx=30, pady=10)
        
        tk.Label(title_container, text="LeafPilot", font=("Segoe UI", 24, "bold"), fg=self.accent_color, bg=self.header_color).pack(side=tk.LEFT)
        tk.Label(title_container, text="v2.0 Performance Edition", font=("Segoe UI", 9), fg="#94a3b8", bg=self.header_color).pack(side=tk.LEFT, padx=10, pady=(10, 0))

        # Main Content Area
        main_container = tk.Frame(self.root, bg=self.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Tabs
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 20))
        
        self.run_tab = ttk.Frame(self.notebook, padding=20)
        self.settings_tab = ttk.Frame(self.notebook, padding=20)
        
        self.notebook.add(self.run_tab, text="  🚀 Automation  ")
        self.notebook.add(self.settings_tab, text="  ⚙️ Settings  ")
        
        self.setup_run_tab()
        self.setup_settings_tab()

        self.setup_footer()

    def setup_run_tab(self):
        # File Selection
        file_frame = tk.Frame(self.run_tab, bg=self.bg_color)
        file_frame.pack(fill=tk.X, pady=(0, 20))
        
        tk.Label(file_frame, text="Recipients CSV:", font=("Segoe UI Semibold", 10), bg=self.bg_color, fg=self.text_color).pack(side=tk.LEFT)
        self.csv_path_var = tk.StringVar(value=self.settings.get("recipients_csv_path", ""))
        self.csv_entry = tk.Entry(file_frame, textvariable=self.csv_path_var, width=65, font=("Segoe UI", 9), relief=tk.FLAT, highlightthickness=1, highlightbackground="#cbd5e1")
        self.csv_entry.pack(side=tk.LEFT, padx=10, ipady=3)
        ttk.Button(file_frame, text="Browse...", command=self.browse_csv).pack(side=tk.LEFT)
        
        # Controls
        ctrl_frame = tk.Frame(self.run_tab, bg=self.bg_color)
        ctrl_frame.pack(fill=tk.X, pady=(0, 20))
        
        self.start_btn = ttk.Button(ctrl_frame, text="🚀 START AUTOMATION", style="Action.TButton", command=self.start_automation)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_btn = ttk.Button(ctrl_frame, text="🛑 STOP", style="Stop.TButton", command=self.stop_automation, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)

        self.headless_var = tk.BooleanVar(value=bool(self.settings.get("headless_mode", False)))
        self.pending_headless: bool | None = None
        self.mode_change_requested = threading.Event()
        self.headless_check = ttk.Checkbutton(
            ctrl_frame,
            text="Headless Mode",
            variable=self.headless_var,
            command=self.on_headless_toggle,
        )
        self.headless_check.pack(side=tk.LEFT, padx=(10, 0))
        
        self.status_var = tk.StringVar(value="Ready to start.")
        tk.Label(ctrl_frame, textvariable=self.status_var, font=("Segoe UI", 9), fg="#64748b", bg=self.bg_color).pack(side=tk.RIGHT)

        # Log Window
        log_frame = tk.LabelFrame(self.run_tab, text=" Activity Log ", font=("Segoe UI Semibold", 10), bg=self.bg_color, fg=self.sidebar_color, padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_widget = scrolledtext.ScrolledText(log_frame, state='disabled', height=15, font=("Consolas", 10), bg="#1e293b", fg="#f1f5f9", borderwidth=0)
        self.log_widget.pack(fill=tk.BOTH, expand=True)

    def setup_settings_tab(self):
        canvas = tk.Canvas(self.settings_tab, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.settings_tab, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        self.vars = {}
        fields = [
            ("Overleaf Project URL", "project_url", "The URL of the base project or template"),
            ("Chrome Profile Path", "user_data_dir", "Path to fixed Chrome profile"),
            ("Output CSV Path", "share_links_csv_path", "Where to save results"),
            ("Email Subject Template", "email_subject_template", "Subject for Gmail notifications"),
        ]
        
        for i, (label, key, hint) in enumerate(fields):
            container = tk.Frame(scrollable_frame, bg=self.bg_color, pady=8)
            container.pack(fill=tk.X)
            tk.Label(container, text=label, font=("Segoe UI Semibold", 9), bg=self.bg_color, width=22, anchor=tk.W).pack(side=tk.LEFT)
            self.vars[key] = tk.StringVar(value=self.settings.get(key, ""))
            tk.Entry(container, textvariable=self.vars[key], width=55, font=("Segoe UI", 9), relief=tk.FLAT, highlightthickness=1, highlightbackground="#e2e8f0").pack(side=tk.LEFT, padx=5, ipady=2)

        tk.Label(scrollable_frame, text="Email Body Template:", font=("Segoe UI Semibold", 9), bg=self.bg_color).pack(anchor=tk.W, pady=(15, 5))
        self.email_body_text = scrolledtext.ScrolledText(scrollable_frame, height=10, width=72, font=("Segoe UI", 10), relief=tk.FLAT, highlightthickness=1, highlightbackground="#e2e8f0")
        self.email_body_text.pack(fill=tk.X, pady=(0, 20))
        self.email_body_text.insert(tk.END, self.settings.get("email_body_template", ""))

        save_btn = ttk.Button(self.settings_tab, text="💾 SAVE ALL SETTINGS", style="Action.TButton", command=self.save_settings)
        save_btn.pack(pady=10)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def setup_footer(self):
        footer_frame = tk.Frame(self.root, bg=self.sidebar_color, height=70)
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)
        footer_frame.pack_propagate(False)

        content_inner = tk.Frame(footer_frame, bg=self.sidebar_color)
        content_inner.pack(expand=True)

        try:
            footer_logo_path = resource_path("ccl pd.jpeg")
            if os.path.exists(footer_logo_path):
                img = Image.open(footer_logo_path)
                img = img.resize((45, 45), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                logo_label = tk.Label(content_inner, image=photo, bg=self.sidebar_color)
                logo_label.image = photo # Keep reference
                logo_label.pack(side=tk.LEFT, padx=10)
        except Exception as e:
            print(f"Warning: Could not load footer logo: {e}")

        footer_text = "This Automation Tool is made by UIU Computer Club Programming Department."
        tk.Label(content_inner, text=footer_text, font=("Segoe UI Semibold", 10), fg="white", bg=self.sidebar_color).pack(side=tk.LEFT)

    def browse_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if file_path:
            self.csv_path_var.set(file_path)

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict) and "project_url" in loaded:
                        loaded["project_url"] = _normalize_project_url(loaded.get("project_url"))
                    return loaded
            except:
                pass
        
        return {
            "project_url": "",
            "user_data_dir": str(Path.home() / ".leafpilot_chrome_profile"),
            "recipients_csv_path": "",
            "share_links_csv_path": "overleaf_share_links.csv",
            "email_subject_template": "Overleaf Project Edit Access: {project_name}",
            "email_body_template": "Dear {leader_name},\n\nI hope you are doing well. I am sharing the Overleaf project {project_name} with edit access.\n\nLink: {link}\n\nTeam Members:\n{team_members}\n\nRegards,\nLeafPilot Automation",
            "headless_mode": False,
        }

    def save_settings(self):
        new_settings = {k: v.get() for k, v in self.vars.items()}
        new_settings["project_url"] = _normalize_project_url(new_settings.get("project_url"))
        new_settings["email_body_template"] = self.email_body_text.get("1.0", tk.END).strip()
        new_settings["recipients_csv_path"] = self.csv_path_var.get()
        new_settings["headless_mode"] = bool(self.headless_var.get())
        
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(new_settings, f, indent=4)
        
        self.settings = new_settings
        messagebox.showinfo("LeafPilot", "Settings saved successfully!")

    def start_automation(self):
        if not self.csv_path_var.get() or not os.path.exists(self.csv_path_var.get()):
            messagebox.showerror("Error", "Please select a valid recipients CSV file first.")
            return
            
        if not self.vars["project_url"].get():
            messagebox.showerror("Error", "Please set the Overleaf Project URL in Settings.")
            return

        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.log_widget.configure(state='normal')
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.configure(state='disabled')
        self.status_var.set("Automation in progress...")
        self.stop_event.clear()
        self.pending_headless = None
        self.mode_change_requested.clear()
        
        print("Initializing LeafPilot Automation...")
        self.automation_thread = threading.Thread(target=self.run_workflow, daemon=True)
        self.automation_thread.start()

    def stop_automation(self):
        print("\n🛑 Stop requested. Finishing current team then stopping...")
        self.stop_event.set()
        self.stop_btn.configure(state=tk.DISABLED)
        self.status_var.set("Stopping (waiting for clean break)...")

    def on_headless_toggle(self):
        if self.automation_thread and self.automation_thread.is_alive():
            self.pending_headless = bool(self.headless_var.get())
            self.mode_change_requested.set()
            print("\n🔄 Mode change requested. Will apply after current team finishes...")
        else:
            self.pending_headless = None

    def run_workflow(self):
        try:
            config_data = {k: v.get() for k, v in self.vars.items()}
            config_data["email_body_template"] = self.email_body_text.get("1.0", tk.END).strip()
            config_data["recipients_csv_path"] = self.csv_path_var.get()
            config_data["headless_mode"] = bool(self.headless_var.get())
            
            config = AppConfig.from_dict(config_data)
            
            browser_manager = ChromeBrowserManager(
                user_data_dir=config.user_data_dir,
                start_maximized=config.start_maximized,
            )

            # Warn if the user set the real Chrome profile — we redirect automatically.
            real_chrome = str(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data")
            if str(config.user_data_dir).lower() == real_chrome.lower():
                print("⚠️  Real Chrome profile detected — using dedicated LeafPilot profile instead.")
                print(f"   Profile: {Path.home() / '.leafpilot_chrome_profile'}")
                print("   (You may need to log in to Overleaf/Gmail on first run)")

            driver = None
            try:
                headless = bool(self.headless_var.get())

                def _create_driver_with_login(use_headless: bool):
                    """
                    Launch Chrome and verify both logins.
                    - Non-headless: single launch, check login directly in that window.
                    - Headless: open a visible window first for manual login if needed,
                      then relaunch headless and do a quick login verification.
                    """
                    if use_headless:
                        print("🔍 Headless mode: verifying login in a visible browser first...")
                        headed_driver = browser_manager.create_driver(headless=False)
                        headed_automation = OverleafProjectSharer(
                            headed_driver,
                            config,
                            stop_event=self.stop_event,
                        )
                        headed_automation.ensure_logged_in()
                        headed_automation.ensure_gmail_logged_in()
                        browser_manager.quit_driver(headed_driver)

                        new_driver = browser_manager.create_driver(headless=True)
                        new_automation = OverleafProjectSharer(
                            new_driver,
                            config,
                            stop_event=self.stop_event,
                        )
                        # Quick sanity check in headless — no manual login possible here
                        new_automation.ensure_logged_in()
                        new_automation.ensure_gmail_logged_in()
                    else:
                        new_driver = browser_manager.create_driver(headless=False)
                        new_automation = OverleafProjectSharer(
                            new_driver,
                            config,
                            stop_event=self.stop_event,
                        )
                        new_automation.ensure_logged_in()
                        new_automation.ensure_gmail_logged_in()

                    return new_driver, new_automation

                recipients = []
                print("🔍 Launching browser and checking login status...")
                driver, automation = _create_driver_with_login(headless)

                print("🔍 Loading recipients...")
                recipients = automation.load_recipients()
                print(f"📄 Loaded {len(recipients)} team groups from CSV.")

                for index, recipient in enumerate(recipients, start=1):
                    if self.stop_event.is_set():
                        break

                    project_name = automation.build_project_name(recipient)
                    print(
                        f"\n➡️ Processing {index}/{len(recipients)}: "
                        f"{project_name} -> {len(recipient.members)} recipients"
                    )

                    automation.open_project_or_template()
                    automation.rename_project(project_name)
                    automation.open_share_dialog()
                    link = automation.set_link_sharing_to_edit_and_copy_link()
                    automation.save_link_to_csv(link, project_name)
                    automation.send_email_via_gmail(
                        recipient=recipient,
                        share_link=link,
                        project_name=project_name,
                    )

                    if self.mode_change_requested.is_set():
                        self.mode_change_requested.clear()
                        new_headless = bool(self.pending_headless)
                        self.pending_headless = None
                        print("\n🔄 Applying mode change for next team...")
                        browser_manager.quit_driver(driver)
                        driver, automation = _create_driver_with_login(new_headless)
                
                if self.stop_event.is_set():
                    print("\n🛑 Automation stopped by user.")
                else:
                    print("\n✅ ALL TASKS COMPLETED SUCCESSFULLY.")
            except Exception as e:
                print(f"\n❌ ERROR: {e}")
                # Print full traceback to the UI log for easier debugging
                print(traceback.format_exc())
            finally:
                browser_manager.quit_driver(driver)
                
        finally:
            self.root.after(0, self.on_automation_finished)

    def on_automation_finished(self):
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.status_var.set("Ready.")

def main():
    root = tk.Tk()
    app = LeafPilotGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
