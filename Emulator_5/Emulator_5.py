import tkinter as tk
from tkinter import ttk
import getpass
import socket
import shlex
import argparse
import hashlib
import csv
import base64
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List
from pathlib import Path
from datetime import datetime


@dataclass
class VFSNode:
    kind: str                     # 'dir' | 'file'
    children: Dict[str, "VFSNode"] = field(default_factory=dict)  # для dir
    content: bytes = b""          # для file
    mode: int = 0o000             # права доступа (восьмеричные)
    mtime: datetime = field(default_factory=lambda: datetime.now().astimezone())

    def is_dir(self) -> bool:
        return self.kind == "dir"

    def is_file(self) -> bool:
        return self.kind == "file"


class VFS:

    def __init__(self):
        self.root = VFSNode(kind="dir", mode=0o755)
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
                node = self._ensure_dir(parts)
                node.mode = node.mode or 0o755
            elif t == "file":
                parent = self._ensure_dir(parts[:-1])
                filename = parts[-1] if parts else None
                if not filename:
                    raise ValueError(f"CSV: некорректный путь к файлу (строка {i})")
                if enc in ("", "utf8", "text"):
                    data_bytes = content.encode("utf-8")
                elif enc in ("base64", "b64", "binary"):
                    data_bytes = base64.b64decode(content.encode("ascii"))
                else:
                    raise ValueError(f"CSV: неизвестная кодировка '{enc}' (строка {i})")
                parent.children[filename] = VFSNode(kind="file", content=data_bytes, mode=0o644)
            else:
                raise ValueError(f"CSV: неизвестный type '{t}' (строка {i})")

    def _ensure_dir(self, parts: List[str]) -> VFSNode:
        cur = self.root
        for name in parts:
            node = cur.children.get(name)
            if node is None:
                node = VFSNode(kind="dir", mode=0o755)
                cur.children[name] = node
            elif node.kind != "dir":
                raise ValueError(f"Путь конфликтует с файлом: {'/'.join(parts)}")
            cur = node
        return cur

    def sha256(self) -> Optional[str]:
        if self._raw_bytes is None:
            return None
        return hashlib.sha256(self._raw_bytes).hexdigest()

    @property
    def name(self) -> Optional[str]:
        return self._name

    # ---------- Разрешение путей ----------

    def resolve(self, cwd_parts: List[str], path: str) -> Tuple[List[str], Optional[VFSNode]]:
        parts: List[str] = [] if path.startswith("/") else list(cwd_parts)
        for seg in path.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(seg)

        node = self.root
        for seg in parts:
            if not node.is_dir():
                return parts, None
            node = node.children.get(seg)
            if node is None:
                return parts, None
        return parts, node

    def resolve_parent(self, cwd_parts: List[str], path: str) -> Tuple[List[str], Optional[VFSNode], Optional[str]]:
        parts: List[str] = [] if path.startswith("/") else list(cwd_parts)
        segs = [s for s in path.split("/") if s not in ("", ".")]
        if not segs:
            return parts, None, None
        basename = segs[-1]
        for seg in segs[:-1]:
            if seg == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(seg)
        node = self.root
        for seg in parts:
            if not node.is_dir():
                return parts, None, basename
            node = node.children.get(seg)
            if node is None:
                return parts, None, basename
        return parts, node, basename


# ---------------- GUI Shell Emulator ----------------

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
        self.cwd_parts: List[str] = []
        self._load_vfs_if_any()

        self.println("Добро пожаловать в эмулятор оболочки (Вариант №18, Этап 5).")
        self.println("Команды: ls [-l] [-a] [path], cd <path>, date, tac <path>, vfs-info, pwd, touch <path>, chmod [-R] <mode> <path>, exit.")
        self.println()

        if self.startup_script:
            self.root.after(100, self._run_startup_script_safe)


    def println(self, text: str = ""):
        self.text.insert("end", text + "\n")
        self.text.see("end")

    def print_prompt_and_command(self, cmd: str):
        self.println(self.prompt + cmd)

    def cwd_str(self) -> str:
        return "/" + "/".join(self.cwd_parts)

    def parse_command_line(self, line: str) -> Tuple[str, List[str], Optional[str]]:
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError as e:
            return "", [], f"Ошибка парсинга: {e}"
        if not tokens:
            return "", [], None
        return tokens[0], tokens[1:], None

    @staticmethod
    def _fmt_mode(node: VFSNode) -> str:
        kind_char = "d" if node.is_dir() else "-"
        return f"{kind_char}{node.mode:04o}"


    def cmd_ls(self, args: List[str]) -> bool:
        long = False
        all_ = False
        i = 0
        while i < len(args) and args[i].startswith("-") and args[i] != "-":
            flags = args[i][1:]
            for ch in flags:
                if ch == "l":
                    long = True
                elif ch == "a":
                    all_ = True
                else:
                    self.println(f"ls: неизвестная опция '-{ch}'")
                    return False
            i += 1

        target = args[i] if i < len(args) else "."

        # Резолвим цель
        parts, node = self.vfs.resolve(self.cwd_parts, target)
        if node is None:
            self.println(f"ls: не удалось открыть '{target}': Нет такого файла или каталога")
            return False

        # Печать одной записи
        def print_entry(name: str, n: VFSNode):
            if long:
                self.println(f"{self._fmt_mode(n)} {name}")
            else:
                self.println(name)

        if node.is_file():
            name = parts[-1] if parts else target
            print_entry(name, node)
            return True

        names = sorted(node.children.keys())

        if not all_:
            names = [n for n in names if not n.startswith(".")]

        entries: List[Tuple[str, VFSNode]] = []
        if all_:
            entries.append((".", node))
            if parts:
                parent = self.vfs.root
                for seg in parts[:-1]:
                    parent = parent.children.get(seg)
                    if parent is None:
                        parent = node
                        break
                entries.append(("..", parent))
            else:
                entries.append(("..", node))

        # Реальные дети
        for name in names:
            entries.append((name, node.children[name]))

        if long:
            for name, child in entries:
                self.println(f"{self._fmt_mode(child)} {name}")
        else:
            if entries:
                self.println("  ".join(name for name, _ in entries))
        return True

    def cmd_cd(self, args: List[str]) -> bool:
        if len(args) != 1:
            self.println("Ошибка: команда 'cd' требует ровно 1 аргумент (путь).")
            return False
        target = args[0]
        parts, node = self.vfs.resolve(self.cwd_parts, target)
        if node is None or not node.is_dir():
            self.println(f"cd: не удалось перейти в '{target}': Нет такого каталога")
            return False
        self.cwd_parts = parts
        return True

    def cmd_date(self) -> bool:
        now = datetime.now().astimezone()
        self.println(now.isoformat(timespec="seconds"))
        return True


    def cmd_tac(self, args: List[str]) -> bool:
        if len(args) != 1:
            self.println("tac: требуется ровно 1 аргумент: путь к файлу")
            return False
        target = args[0]
        parts, node = self.vfs.resolve(self.cwd_parts, target)
        if node is None:
            self.println(f"tac: '{target}': Нет такого файла")
            return False
        if not node.is_file():
            self.println(f"tac: '{target}': это каталог")
            return False
        try:
            text = node.content.decode("utf-8")
        except UnicodeDecodeError:
            self.println(f"tac: '{target}': невозможно декодировать как UTF-8")
            return False

        chunks = re.findall(r'.*?\n|.+\Z', text, flags=re.DOTALL)
        for chunk in reversed(chunks):
            if chunk.endswith("\n"):
                self.println(chunk[:-1])
            else:
                self.println(chunk)
        return True


    def cmd_touch(self, args: List[str]) -> bool:
        if len(args) != 1:
            self.println("touch: требуется ровно 1 аргумент: путь к файлу")
            return False
        target = args[0]
        parent_parts, parent_node, basename = self.vfs.resolve_parent(self.cwd_parts, target)
        if parent_node is None or not parent_node.is_dir():
            self.println(f"touch: не удалось создать '{target}': Родительский каталог не найден")
            return False
        _, node = self.vfs.resolve(self.cwd_parts, target)
        now = datetime.now().astimezone()
        if node:
            node.mtime = now
            self.println(f"touch: обновлён mtime '{target}'")
            return True
        parent_node.children[basename] = VFSNode(kind="file", content=b"", mode=0o644, mtime=now)
        self.println(f"touch: создан пустой файл '{target}'")
        return True

    def _chmod_apply_symbolic(self, cur_mode: int, clause: str, is_dir: bool) -> int:
        i = 0
        classes = ""
        while i < len(clause) and clause[i] in "ugoa":
            classes += clause[i]
            i += 1
        if not classes:
            classes = "a"
        if i >= len(clause) or clause[i] not in "+-=":
            raise ValueError(f"неверный синтаксис chmod: '{clause}'")
        op = clause[i]
        i += 1
        if i >= len(clause):
            raise ValueError(f"неверный синтаксис chmod: '{clause}'")
        perms = clause[i:]
        if not all(c in "rwxX" for c in perms):
            raise ValueError(f"неверные права в chmod: '{perms}'")

        def bits_for(perms_local: str, cls_char: str) -> int:
            shift = {"u": 6, "g": 3, "o": 0}[cls_char]
            mask = 0
            for ch in perms_local:
                if ch == "r":
                    mask |= (0o4 << shift)
                elif ch == "w":
                    mask |= (0o2 << shift)
                elif ch == "x":
                    mask |= (0o1 << shift)
                elif ch == "X":
                    exec_any = (cur_mode & 0o111) != 0
                    if is_dir or exec_any:
                        mask |= (0o1 << shift)
            return mask

        class_mask_all = 0
        for cls in classes:
            class_mask_all |= {
                "u": 0o700,
                "g": 0o070,
                "o": 0o007,
                "a": 0o777,
            }[cls]

        new_mode = cur_mode

        if op == "=":
            set_mask = 0
            for cls in ("u", "g", "o"):
                if ("a" in classes) or (cls in classes):
                    set_mask |= bits_for(perms, cls)
            new_mode = (new_mode & ~class_mask_all) | (set_mask & class_mask_all)
        elif op == "+":
            add_mask = 0
            for cls in ("u", "g", "o"):
                if ("a" in classes) or (cls in classes):
                    add_mask |= bits_for(perms, cls)
            new_mode |= add_mask
        elif op == "-":
            sub_mask = 0
            for cls in ("u", "g", "o"):
                if ("a" in classes) or (cls in classes):
                    sub_mask |= bits_for(perms, cls)
            new_mode &= ~sub_mask
        else:
            raise ValueError(f"неизвестная операция chmod: '{op}'")

        new_mode &= 0o777
        return new_mode

    def _chmod_walk(self, node: VFSNode, recursive: bool):
        """Итерация по узлу и (опц.) всем дочерним для -R."""
        yield node
        if recursive and node.is_dir():
            for _, child in node.children.items():
                yield from self._chmod_walk(child, True)


    def cmd_chmod(self, args: List[str]) -> bool:
        if not args:
            self.println("chmod: требуется 2 аргумента: <mode> <path> (опционально -R перед mode)")
            return False

        recursive = False
        i = 0
        if args[0] == "-R":
            recursive = True
            i += 1
        if len(args) - i != 2:
            self.println("chmod: требуется 2 аргумента: <mode> <path>")
            return False

        mode_spec = args[i]
        target = args[i + 1]

        parts, node = self.vfs.resolve(self.cwd_parts, target)
        if node is None:
            self.println(f"chmod: не удалось применить к '{target}': Нет такого файла или каталога")
            return False

        is_numeric = (len(mode_spec) in (3, 4)) and all(c in "01234567" for c in mode_spec)

        try:
            if is_numeric:
                mode_val = int(mode_spec, 8) & 0o777
                for n in self._chmod_walk(node, recursive):
                    n.mode = mode_val
                self.println(f"chmod: установлен {mode_val:04o} для '{target}'" + (" (рекурсивно)" if recursive else ""))
                return True
            else:
                clauses = [c.strip() for c in mode_spec.split(",") if c.strip()]
                if not clauses:
                    self.println(f"chmod: неверный режим '{mode_spec}'")
                    return False
                for n in self._chmod_walk(node, recursive):
                    cur = n.mode
                    for clause in clauses:
                        cur = self._chmod_apply_symbolic(cur, clause, is_dir=n.is_dir())
                    n.mode = cur & 0o777
                self.println(f"chmod: применён символьный режим '{mode_spec}' для '{target}'" + (" (рекурсивно)" if recursive else ""))
                return True
        except ValueError as e:
            self.println(f"chmod: {e}")
            return False

    def exec(self, line: str) -> Tuple[bool, bool]:
        cmd, args, perr = self.parse_command_line(line)
        if perr:
            self.println(perr)
            return False, False
        if not cmd:
            return True, False
        try:
            if cmd == "ls":
                ok = self.cmd_ls(args); return ok, False
            elif cmd == "cd":
                ok = self.cmd_cd(args); return ok, False
            elif cmd == "date":
                ok = self.cmd_date(); return ok, False
            elif cmd == "tac":
                ok = self.cmd_tac(args); return ok, False
            elif cmd == "touch":
                ok = self.cmd_touch(args); return ok, False
            elif cmd == "chmod":
                ok = self.cmd_chmod(args); return ok, False
            elif cmd == "vfs-info":
                if self.vfs.name is None:
                    self.println("VFS не загружена.")
                else:
                    self.println(f"VFS: name={self.vfs.name}, sha256={self.vfs.sha256()}")
                return True, False
            elif cmd == "pwd":
                self.println(self.cwd_str()); return True, False
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

        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
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
    p = argparse.ArgumentParser(description="Эмулятор оболочки — Вариант №18, Этап 5")
    p.add_argument("--vfs", type=str, default=None, help="Путь к CSV-файлу VFS")
    p.add_argument("--startup", type=str, default=None, help="Путь к стартовому скрипту")
    return p.parse_args()


def main():
    args = parse_args()
    root = tk.Tk()
    app = ShellEmulatorGUI(root, vfs_path=args.vfs, startup_script=args.startup)
    root.geometry("900x600")
    root.minsize(720, 440)
    root.mainloop()


if __name__ == "__main__":
    main()
