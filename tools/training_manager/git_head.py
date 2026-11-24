"""Resolve Git and read the commit for the intended checkout."""

from itertools import chain
import os
from pathlib import Path
import re
import shutil
import subprocess


def path_git():
    if os.name != "nt":
        executable = shutil.which("git")
        if executable:
            yield Path(executable)
        return
    # On older Windows Python, shutil.which also searches the current directory.
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(os.path.expandvars(entry.strip().strip('"')))
        if directory.is_absolute():
            yield directory / "git.exe"


def registered_git_roots():
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\GitForWindows", 0, winreg.KEY_READ | view) as key:
                    value, _ = winreg.QueryValueEx(key, "InstallPath")
            except OSError:
                continue
            if isinstance(value, str):
                yield Path(os.path.expandvars(value))


def desktop_git_roots(local_appdata):
    versions = []
    for directory in (local_appdata / "GitHubDesktop").glob("app-*"):
        match = re.fullmatch(r"app-(\d+(?:\.\d+)*)(-[\w.-]+)?", directory.name)
        if match:
            version = tuple(map(int, match[1].split(".")))
            versions.append((version, match[2] is None, directory))
    for _, _, directory in sorted(versions, reverse=True):
        yield directory / "resources" / "app" / "git"


def candidates():
    yield from path_git()
    if os.name != "nt":
        return
    # A restricted parent process may redirect LOCALAPPDATA away from the user profile.
    local = [Path.home() / "AppData" / "Local"]
    if local_appdata := os.environ.get("LOCALAPPDATA"):
        local.insert(0, Path(local_appdata))
    locations = [Path(os.environ[name]) / "Git" for name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
                 if os.environ.get(name)]
    locations.extend(directory / "Programs" / "Git" for directory in local)
    desktop = (git for directory in dict.fromkeys(local) for git in desktop_git_roots(directory))
    for root in chain(registered_git_roots(), locations, desktop):
        if root.is_absolute():
            yield root / "cmd" / "git.exe"
            yield root / "bin" / "git.exe"


def checkout_head(root):
    # Environment inherited from another Git process must not select a different repository.
    overrides = {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_NAMESPACE",
                 "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_INDEX_FILE"}
    env = {key: value for key, value in os.environ.items() if key.upper() not in overrides}
    last_error = None
    seen = set()
    for executable in candidates():
        if executable in seen or not executable.is_file():
            continue
        seen.add(executable)
        try:
            result = subprocess.run(
                [str(executable.absolute()), "rev-parse", "--show-toplevel", "--verify", "HEAD^{commit}"],
                cwd=root, env=env, check=True, capture_output=True, encoding="utf-8", errors="replace",
                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.CalledProcessError as error:
            last_error = error.stderr.strip() or f"Git 退出码 {error.returncode}"
            continue
        except subprocess.TimeoutExpired:
            last_error = "Git 查询超时"
            continue
        except OSError:
            last_error = "Git 可执行文件无法启动"
            continue
        lines = result.stdout.splitlines()
        if len(lines) != 2 or not re.fullmatch(r"[a-f0-9]{40}", lines[1]):
            last_error = "Git 未返回完整的 HEAD 提交哈希"
            continue
        if Path(lines[0]).resolve() != root.resolve():
            last_error = "Git 返回的仓库根目录与当前项目不一致"
            continue
        return lines[1]
    if last_error:
        raise ValueError(f"无法核验当前项目的 Git HEAD。请确认打开的是完整的项目仓库。详情：{last_error}")
    raise ValueError("找不到可执行的 Git。请确认当前 Windows 用户已安装 Git for Windows 或 GitHub Desktop，"
                     "然后退出并重新打开训练面板。冻结需要读取当前提交。")
