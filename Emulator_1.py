import tkinter as tk
from tkinter import ttk
import getpass
import socket
import shlex
import sys


class ShellEmulatorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        user = getpass.getuser() or "user"
        try:
            host = socket.gethostname() or "host"
        except Exception:
            host = "host"
        self.user, self.host = user, host

        self.prompt = f"[{self.user}@{self.host}]$ "
        self.root.title(f"Эмулятор - [{self.user}@{self.host}]")

        self.text = tk.Text(root, wrap="word", font=("Courier New", 12), state="normal")
        self.text.configure(height=20)
        self.scroll = ttk.Scrollbar(root, command=self.text.yview)
        self.text["yscrollcommand"] = self.scroll.set

        self.entry = ttk.Entry(root, font=("Courier New", 12))
        self.btn = ttk.Button(root, text="Ввод", command=self.handle_submit)

        self.text.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.scroll.grid(row=0, column=2, sticky="ns")
        self.entry.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(4, 0))
        self.btn.grid(row=1, column=1, sticky="ew", pady=(4, 0))

        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=0)
        root.rowconfigure(0, weight=1)

        self.entry.bind("<Return>", lambda e: self.handle_submit())

        self.println("Добро пожаловать в эмулятор оболочки (Вариант №18, Этап 1).")
        self.println("Доступные команды: ls, cd <путь>, exit.")
        self.println('Поддерживаются аргументы в кавычках, напр.: ls "/path with spaces"')
        self.println()

        self.entry.focus_set()

    def println(self, text: str = ""):
        self.text.insert("end", text + "\n")
        self.text.see("end")

    def print_prompt_and_command(self, cmd: str):
        self.println(self.prompt + cmd)

    def parse_command_line(self, line: str):
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError as e:
            return "", [], f"Ошибка парсинга: {e}"
        if not tokens:
            return "", [], None
        return tokens[0], tokens[1:], None

    def exec(self, line: str):
        cmd, args, perr = self.parse_command_line(line)
        if perr:
            self.println(perr)
            return
        if not cmd:
            return
        try:
            if cmd == "ls":
                self.println(f"ls: args={args}")
            elif cmd == "cd":
                if len(args) != 1:
                    self.println(f"Ошибка: команда 'cd' требует ровно 1 аргумент (путь). Получено: {len(args)}")
                else:
                    self.println(f"cd: args={args}")
            elif cmd == "exit":
                self.println("Завершение работы эмулятора.")
                self.root.after(200, self.root.destroy)
            else:
                self.println(f"Ошибка: неизвестная команда '{cmd}'")
        except Exception as e:
            self.println(f"Ошибка выполнения команды '{cmd}': {e}")

    def handle_submit(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.print_prompt_and_command(text)
        self.exec(text)
        self.entry.delete(0, "end")
        self.entry.focus_set()


def main():
    root = tk.Tk()
    app = ShellEmulatorGUI(root)
    root.geometry("900x600")
    root.minsize(600, 400)
    root.mainloop()


if __name__ == "__main__":
    main()
