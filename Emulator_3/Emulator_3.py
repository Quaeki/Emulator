
import tkinter as tk
from tkinter import ttk
import getpass
import socket
import shlex
import argparse
import hashlib
import csv
import base64
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List
from pathlib import Path


@dataclass
class VFSNode:
    kind: str
    children: Dict[str, "VFSNode"] = field(default_factory=dict)  # for dirs
    content: bytes = b""

    def is_dir(self) -> bool:
        return self.kind == "dir"

    def is_file(self) -> bool:
        return self.kind == "file"


class VFS:

    def __init__(self):
        self.root = VFSNode(kind="dir")
        self._raw_bytes: Optional[bytes] = None
        self._name: Optional[str] = None

    def load_from_csv(self, path: str):
        data = Path(path).read_bytes()
        self._raw_bytes = data
        self._name = Path(path).name
        text = data.decode("utf-8")
        reader = csv.DictReader(text.splitlines())
        for i, row in enumerate(reader, start=2):
            p = (row.get("path") or "").strip()
            t = (row.get("type") or "").strip().lower()
            enc = (row.get("encoding") or "").strip().lower()
            content = row.get("content") or ""
            if not p or not t:
                raise ValueError(f"CSV: пустой path/type (строка {i})")
            parts = [seg for seg in p.split("/") if seg not in ("", ".")]
            if t == "dir":
                self._ensure_dir(parts)
            elif t == "file":
                if not parts:
                    raise ValueError(f"CSV: некорректный путь к файлу (строка {i})")
                parent = self._ensure_dir(parts[:-1])
                filename = parts[-1]
                if enc in ("", "utf8", "text"):
                    data_bytes = content.encode("utf-8")
                elif enc in ("base64", "b64", "binary"):
                    try:
                        data_bytes = base64.b64decode(content.encode("ascii"))
                    except Exception as e:
                        raise ValueError(f"CSV: не удалось декодировать base64 (строка {i}): {e}")
                else:
                    raise ValueError(f"CSV: неизвестная кодировка '{enc}' (строка {i})")
                parent.children[filename] = VFSNode(kind="file", content=data_bytes)
            else:
                raise ValueError(f"CSV: неизвестный type '{t}' (строка {i})")

    def _ensure_dir(self, parts: List[str]) -> VFSNode:
        cur = self.root
        for name in parts:
            node = cur.children.get(name)
            if node is None:
                node = VFSNode(kind="dir")
                cur.children[name] = node
            elif node.kind != "dir":
                raise ValueError(f"Путь конфликтует с файлом: {'/'.join(parts)}")
            cur = node
        return cur

    @property
    def name(self) -> Optional[str]:
        return self._name

    def sha256(self) -> Optional[str]:
        if self._raw_bytes is None:
            return None
        return hashlib.sha256(self._raw_bytes).hexdigest()

class ShellEmulatorGUI:

    def __init__(self, root: tk.Tk, vfs_path: Optional[str], startup_script: Optional[str]):
        self.root = root
        self.vfs_path = vfs_path
        self.startup_script = startup_script

        user = getpass.getuser() or "user"
        try:
            host = socket.gethostname() or "host"
        except Exception:
            host = "host"
        self.user, self.host = user, host
        self.prompt = f"[{self.user}@{self.host}]$ "
        self.root.title(f"Эмулятор - [{self.user}@{self.host}]")

        # UI
        self.text = tk.Text(root, wrap="word", font=("Courier New", 12), state="normal")
        self.scroll = ttk.Scrollbar(root, command=self.text.yview)
        self.text["yscrollcommand"] = self.scroll.set
        self.entry = ttk.Entry(root, font=("Courier New", 12))
        self.btn = ttk.Button(root, text="Ввод", command=self.handle_submit)

        self.text.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.scroll.grid(row=0, column=2, sticky="ns")
        self.entry.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(4, 0))
        self.btn.grid(row=1, column=1, sticky="ew", pady=(4, 0))

        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.entry.bind("<Return>", lambda e: self.handle_submit())
        self.entry.focus_set()

        self.vfs = VFS()
        self._load_vfs_if_any()

        self.println("Добро пожаловать в эмулятор оболочки (Вариант №18, Этап 3: VFS CSV).")
        self.println("Доступные команды: ls, cd <путь>, exit, vfs-info.")
        self.println('Поддерживаются аргументы в кавычках, напр.: ls "/path with spaces"')
        self.println()
        self.println("[конфигурация] Параметры запуска:")
        self.println(f"[конфигурация] vfs_path = {self.vfs_path!r}")
        self.println()

        if self.startup_script:
            self.root.after(100, self._run_startup_script_safe)

    def println(self, text: str = ""):
        self.text.insert("end", text + "\n")
        self.text.see("end")

    def print_prompt_and_command(self, cmd: str):
        self.println(self.prompt + cmd)

    def parse_command_line(self, line: str) -> Tuple[str, List[str], Optional[str]]:
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError as e:
            return "", [], f"Ошибка парсинга: {e}"
        if not tokens:
            return "", [], None
        return tokens[0], tokens[1:], None

    def exec(self, line: str) -> Tuple[bool, bool]:
        cmd, args, perr = self.parse_command_line(line)
        if perr:
            self.println(perr)
            return False, False
        if not cmd:
            return True, False

        try:
            if cmd == "ls":
                self.println(f"ls: args={args}")
                return True, False
            elif cmd == "cd":
                if len(args) != 1:
                    self.println(f"Ошибка: команда 'cd' требует ровно 1 аргумент (путь). Получено: {len(args)}")
                    return False, False
                self.println(f"cd: args={args}")
                return True, False
            elif cmd == "vfs-info":
                if self.vfs.name is None:
                    self.println("VFS не загружена.")
                else:
                    self.println(f"VFS: name={self.vfs.name}, sha256={self.vfs.sha256()}")
                return True, False
            elif cmd == "exit":
                self.println("Завершение работы эмулятора.")
                self.root.after(200, self.root.destroy)
                return True, True
            else:
                self.println(f"Ошибка: неизвестная команда '{cmd}'")
                return False, False
        except Exception as e:
            self.println(f"Ошибка выполнения команды '{cmd}': {e}")
            return False, False

    def _load_vfs_if_any(self):
        if not self.vfs_path:
            return
        try:
            self.vfs.load_from_csv(self.vfs_path)
            self.println(f"[vfs] Загружена VFS из CSV: {self.vfs.name}")
        except FileNotFoundError:
            self.println(f"[vfs] Ошибка: файл не найден: {self.vfs_path!r}")
        except Exception as e:
            self.println(f"[vfs] Ошибка загрузки VFS: {e}")

    def _run_startup_script_safe(self):
        path = self.startup_script
        try:
            text = Path(path).read_text(encoding="utf-8")
            lines = text.splitlines()
        except FileNotFoundError:
            self.println(f"[скрипт] Ошибка: файл не найден: {path!r}")
            return
        except Exception as e:
            self.println(f"[скрипт] Ошибка чтения файла {path!r}: {e}")
            return

        self._script_lines = [(i + 1, line) for i, line in enumerate(lines)]
        self._script_index = 0
        self.println(f"[скрипт] Запуск скрипта: {path}")
        self.root.after(0, self._process_next_script_line)

    def _process_next_script_line(self):
        if self._script_index >= len(self._script_lines):
            self.println("[скрипт] Выполнение завершено без ошибок.")
            return

        lineno, line = self._script_lines[self._script_index]
        self._script_index += 1

        if line.strip() == "":
            self.root.after(0, self._process_next_script_line)
            return

        self.print_prompt_and_command(line)
        ok, terminate = self.exec(line)

        if terminate:
            return
        if not ok:
            self.println(f"[скрипт] Остановлен из-за ошибки на строке {lineno}.")
            return

        self.root.after(0, self._process_next_script_line)

    def handle_submit(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.print_prompt_and_command(text)
        self.exec(text)
        self.entry.delete(0, "end")
        self.entry.focus_set()


def parse_args():
    p = argparse.ArgumentParser(description="Эмулятор оболочки — Вариант №18, Этап 3 (VFS из CSV)")
    p.add_argument("--vfs", type=str, default=None, help="Путь к CSV-файлу VFS")
    p.add_argument("--startup", type=str, default=None, help="Путь к стартовому скрипту")
    return p.parse_args()


def main():
    args = parse_args()
    root = tk.Tk()
    app = ShellEmulatorGUI(root, vfs_path=args.vfs, startup_script=args.startup)
    root.geometry("900x600")
    root.minsize(600, 400)
    root.mainloop()


if __name__ == "__main__":
    main()
