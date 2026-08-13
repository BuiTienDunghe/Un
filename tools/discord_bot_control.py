from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from discord_bot.control import (  # noqa: E402
    BotControlError,
    DiscordBotController,
)

MUTEX_NAME = "Local\\LocalAICoreDiscordBotControl"
ERROR_ALREADY_EXISTS = 183


def acquire_single_instance() -> int | None:
    if sys.platform != "win32":
        return 1
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise OSError("Windows could not create the Control Panel mutex.")
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return None
    return int(handle)


def release_single_instance(handle: int) -> None:
    if sys.platform == "win32":
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


class DiscordBotControlPanel:
    def __init__(self, window: tk.Tk) -> None:
        self.window = window
        self.controller = DiscordBotController(REPO_ROOT)
        self.busy = False
        self.closing = False
        self.operation_lock = threading.Lock()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        window.title("Local AI Core — Discord Bot Control")
        window.geometry("720x520")
        window.minsize(660, 470)
        window.protocol("WM_DELETE_WINDOW", self.on_close)

        frame = ttk.Frame(window, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="Discord Bot Control",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            frame,
            text="Persistent shared sessions • explicit Start / Stop / Update",
        ).pack(anchor=tk.W, pady=(0, 14))

        config = ttk.LabelFrame(frame, text="Configuration", padding=10)
        config.pack(fill=tk.X)
        ttk.Label(config, text="Status channel ID:").grid(
            row=0,
            column=0,
            sticky=tk.W,
        )
        self.channel_id = tk.StringVar(
            value=self.controller.configured_channel_id(),
        )
        ttk.Entry(config, textvariable=self.channel_id, width=32).grid(
            row=0,
            column=1,
            sticky=tk.EW,
            padx=8,
        )
        ttk.Button(config, text="Save", command=self.save_channel).grid(
            row=0,
            column=2,
        )
        ttk.Label(
            config,
            text="Enable Discord Developer Mode → Copy Channel ID. Token stays in .env.",
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))
        config.columnconfigure(1, weight=1)

        status_frame = ttk.LabelFrame(frame, text="Runtime status", padding=10)
        status_frame.pack(fill=tk.X, pady=12)
        self.backend_status = tk.StringVar(value="Checking…")
        self.bot_status = tk.StringVar(value="Checking…")
        self.gateway_status = tk.StringVar(value="Checking…")
        self.flag_status = tk.StringVar(value="true (controller policy)")
        self.pid_status = tk.StringVar(value="—")
        rows = (
            ("Backend", self.backend_status),
            ("Bot", self.bot_status),
            ("Discord Gateway", self.gateway_status),
            ("Persistent sessions", self.flag_status),
            ("Process PIDs", self.pid_status),
        )
        for row, (label, value) in enumerate(rows):
            ttk.Label(status_frame, text=f"{label}:").grid(
                row=row,
                column=0,
                sticky=tk.W,
                pady=2,
            )
            ttk.Label(status_frame, textvariable=value).grid(
                row=row,
                column=1,
                sticky=tk.W,
                padx=12,
                pady=2,
            )

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X)
        self.start_button = ttk.Button(
            buttons,
            text="Start Bot",
            command=lambda: self.run_action("start"),
        )
        self.stop_button = ttk.Button(
            buttons,
            text="End Bot",
            command=lambda: self.run_action("end"),
        )
        self.update_button = ttk.Button(
            buttons,
            text="Update / Reload",
            command=lambda: self.run_action("update"),
        )
        self.refresh_button = ttk.Button(
            buttons,
            text="Refresh",
            command=self.refresh,
        )
        self.logs_button = ttk.Button(
            buttons,
            text="Open Logs",
            command=self.open_logs,
        )
        for button in (
            self.start_button,
            self.stop_button,
            self.update_button,
            self.refresh_button,
            self.logs_button,
        ):
            button.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(frame, text="Activity").pack(anchor=tk.W, pady=(14, 4))
        self.activity = tk.Text(
            frame,
            height=10,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        self.activity.pack(fill=tk.BOTH, expand=True)
        self.append_activity(
            "Ready. Start turns the bot on; End turns it off; Update reloads "
            "backend/bot source. Closing this window always performs End."
        )
        self.window.after(100, self.drain_events)
        self.refresh()

    def append_activity(self, text: str) -> None:
        self.activity.configure(state=tk.NORMAL)
        self.activity.insert(tk.END, text + "\n")
        self.activity.see(tk.END)
        self.activity.configure(state=tk.DISABLED)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for button in (
            self.start_button,
            self.stop_button,
            self.update_button,
            self.refresh_button,
        ):
            button.configure(state=state)

    def save_channel(self, *, show_error: bool = True) -> bool:
        try:
            self.controller.save_local_settings(self.channel_id.get())
        except BotControlError as error:
            if show_error:
                messagebox.showerror("Invalid channel", str(error))
            return False
        self.append_activity("Saved the status channel locally.")
        return True

    def drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "status":
                    process, backend = payload
                    if not self.closing:
                        self.apply_status(process, backend)
                elif event == "status_error":
                    if not self.closing:
                        self.append_activity(str(payload))
                elif event == "action":
                    if not self.closing:
                        success, message = payload
                        self.finish_action(bool(success), str(message))
                elif event == "closed":
                    self.destroy_window()
                    return
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.window.after(100, self.drain_events)

    def refresh(self) -> None:
        if self.busy or self.closing:
            return

        def worker() -> None:
            try:
                process = self.controller.status()
                backend = self.controller.backend_healthy()
                self.events.put(("status", (process, backend)))
            except Exception as error:
                self.events.put(
                    (
                        "status_error",
                        f"Status check failed: {type(error).__name__}: {error}",
                    )
                )

        threading.Thread(target=worker, daemon=True).start()

    def apply_status(self, process, backend: bool) -> None:
        self.backend_status.set("Healthy" if backend else "Unavailable")
        if process.duplicate_instances:
            self.bot_status.set("Multiple instances detected")
        elif process.docker_container_running:
            self.bot_status.set("Running in Docker (unmanaged)")
        else:
            self.bot_status.set("Running" if process.running else "Stopped")
        self.gateway_status.set(
            "Connected"
            if process.gateway_connected
            else ("Not detected" if process.running else "Disconnected")
        )
        if process.persistent_sessions_enabled is True:
            self.flag_status.set("true")
        elif process.persistent_sessions_enabled is False:
            self.flag_status.set("false — legacy path")
        else:
            self.flag_status.set("unknown" if process.running else "true on next Start")
        self.pid_status.set(
            ", ".join(map(str, process.process_pids))
            if process.process_pids
            else "—"
        )

    def run_action(self, action: str) -> None:
        if self.busy or self.closing or not self.save_channel():
            return
        channel_id = self.channel_id.get().strip()

        self.set_busy(True)
        self.append_activity(f"{action.title()} requested…")

        def worker() -> None:
            try:
                with self.operation_lock:
                    operation = (
                        self.controller.stop
                        if action == "end"
                        else getattr(self.controller, action)
                    )
                    result = operation(channel_id)
            except Exception as error:
                self.events.put(
                    (
                        "action",
                        (False, f"{type(error).__name__}: {error}"),
                    )
                )
                return
            self.events.put(
                ("action", (result.success, result.message))
            )

        threading.Thread(target=worker, daemon=True).start()

    def finish_action(self, success: bool, message: str) -> None:
        self.set_busy(False)
        self.append_activity(("OK: " if success else "ERROR: ") + message)
        if not success:
            messagebox.showerror("Discord Bot Control", message)
        self.refresh()

    def open_logs(self) -> None:
        self.controller.runtime_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(self.controller.runtime_dir)  # type: ignore[attr-defined]

    def on_close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.controller.request_abort()
        self.set_busy(True)
        self.append_activity("Window close requested — performing End…")
        channel_id = self.channel_id.get().strip()
        if channel_id:
            self.save_channel(show_error=False)

        def worker() -> None:
            try:
                with self.operation_lock:
                    result = self.controller.stop(channel_id or None)
                self.controller._log(
                    "Control Panel closed after End: " + result.message
                )
            except Exception as error:
                self.controller._log(
                    "Control Panel close forced after End error: "
                    f"{type(error).__name__}: {error}"
                )
                # End must still mean the bot process is gone even when a
                # backend/Discord notification is unavailable.
                self.controller._terminate_processes()
                self.controller._clear_state()
            finally:
                self.events.put(("closed", None))

        threading.Thread(target=worker, daemon=True).start()
        # A broken network or native dependency must never make the switch
        # impossible to close. The bot process is killed before forced exit.
        self.window.after(45_000, self.force_close)

    def force_close(self) -> None:
        if not self.closing or not self.window.winfo_exists():
            return
        self.controller.request_abort()
        self.controller._terminate_processes()
        self.controller._clear_state()
        self.controller._log(
            "Control Panel close watchdog forced local bot termination."
        )
        self.destroy_window()

    def destroy_window(self) -> None:
        try:
            self.window.quit()
        finally:
            if self.window.winfo_exists():
                self.window.destroy()


def main() -> None:
    instance_handle = acquire_single_instance()
    if instance_handle is None:
        window = tk.Tk()
        window.withdraw()
        messagebox.showinfo(
            "Discord Bot Control",
            "Discord Bot Control is already open.",
        )
        window.destroy()
        return
    window = tk.Tk()
    DiscordBotControlPanel(window)
    try:
        window.mainloop()
    finally:
        try:
            if window.winfo_exists():
                window.destroy()
        except tk.TclError:
            pass
        release_single_instance(instance_handle)


if __name__ == "__main__":
    main()
