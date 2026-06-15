"""
Auto-updater for Chaser's Shenanigans (run-from-source).

The suite is installed by cloning / downloading this repo and running it with
`python launcher.py` (via run.bat). There is no built .exe and no GitHub
Release to pull, so "update" here means: fetch the latest commit on `main`,
and if we're behind, download that commit's source zip and overlay it onto the
install, then offer to restart.

Design rules this module commits to
-----------------------------------
* **Fail-safe.** Any failure (offline, GitHub down, half-finished download,
  bad zip) must NEVER stop the app launching. Every entry point falls back to
  "carry on with the version already on disk". A photo tool that won't open
  because GitHub is having a bad day is worse than one a commit behind.
* **Overlay, never wipe.** We copy the new files *over* the install and never
  delete local-only files, so `.venv/`, the local update marker, scratch photo
  folders and generated shortcuts all survive an update untouched.
* **Dependencies.** If a pulled commit changes `requirements.txt`, replacing
  .py files isn't enough — new code may import something the .venv doesn't have
  yet. We detect that and re-run pip into the .venv (and if there's no .venv,
  we say so rather than pretend it worked).
* **First run syncs.** With no Releases/tags and possibly no `.git` (people
  download the ZIP), we track the synced commit in a local `.update_state.json`.
  On the very first launch there's no marker and we can't tell a fresh-current
  copy from a stale one, so we sync to the latest commit straight away — quietly,
  only prompting for a restart if the pulled code actually differs from what's on
  disk. After that first sync the marker exists and later launches just compare.

Pure logic (network / file work) is kept free of Qt so it can be tested
head-less; only `run_update_check()` touches the GUI.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import hashlib
import logging
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

# --- What we track and where -------------------------------------------------
REPO_OWNER = "PufferfishGaming"
REPO_NAME = "Chaser-s-Shenanigans"
BRANCH = "main"

_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
_COMMIT_URL = f"{_API}/commits/{BRANCH}"
# Archive host (codeload) is NOT bound by the API's 60/hr unauthenticated limit,
# so the heavy download never competes with the lightweight commit check.
_ZIP_URL = f"https://codeload.github.com/{REPO_OWNER}/{REPO_NAME}/zip/refs/heads/{BRANCH}"
_USER_AGENT = "ChasersShenanigans-Updater"

STATE_FILE = ".update_state.json"
CHECK_TIMEOUT = 4          # seconds — kept short; this is on the launch path
DOWNLOAD_TIMEOUT = 60      # seconds — only after the user opts in

# Local-only things an overlay must never clobber or carry into the copy.
_SKIP_TOP_LEVEL = {".git", ".venv", "venv", "env", STATE_FILE, "__pycache__"}


def app_dir() -> str:
    """The install directory (where this module and launcher.py live)."""
    return os.path.dirname(os.path.abspath(__file__))


# --- Local state -------------------------------------------------------------
def _state_path() -> str:
    return os.path.join(app_dir(), STATE_FILE)


def current_sha() -> str | None:
    try:
        with open(_state_path(), "r", encoding="utf-8") as fh:
            return json.load(fh).get("sha")
    except (OSError, ValueError):
        return None


def _write_sha(sha: str) -> None:
    try:
        with open(_state_path(), "w", encoding="utf-8") as fh:
            json.dump({"sha": sha}, fh)
    except OSError as exc:
        logger.warning("Could not write update marker: %s", exc)


# --- Remote queries ----------------------------------------------------------
def _get(url: str, timeout: int, accept: str = "application/vnd.github+json"):
    req = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": accept})
    return urlopen(req, timeout=timeout)


def latest_remote() -> dict | None:
    """{'sha', 'short', 'message'} for the head of `main`, or None on any error."""
    try:
        with _get(_COMMIT_URL, CHECK_TIMEOUT) as resp:
            data = json.load(resp)
        sha = data["sha"]
        msg = (data.get("commit", {}).get("message") or "").strip().splitlines()
        return {"sha": sha, "short": sha[:7], "message": msg[0] if msg else ""}
    except (URLError, HTTPError, ValueError, KeyError, OSError) as exc:
        logger.info("Update check skipped (could not reach GitHub): %s", exc)
        return None


# --- Applying an update ------------------------------------------------------
def _overlay_tree(src_root: str, dst_root: str) -> None:
    """Copy every file under src_root over dst_root, creating dirs as needed.

    Additive: files that exist in dst but not src are left alone.
    """
    for dirpath, dirnames, filenames in os.walk(src_root):
        rel = os.path.relpath(dirpath, src_root)
        # Don't descend into things we never want to import from the download.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_TOP_LEVEL]
        target_dir = dst_root if rel == "." else os.path.join(dst_root, rel)
        os.makedirs(target_dir, exist_ok=True)
        for name in filenames:
            shutil.copy2(os.path.join(dirpath, name), os.path.join(target_dir, name))


def _venv_python() -> str | None:
    win = os.path.join(app_dir(), ".venv", "Scripts", "python.exe")
    nix = os.path.join(app_dir(), ".venv", "bin", "python")
    for p in (win, nix):
        if os.path.exists(p):
            return p
    return None


def _read(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _code_fingerprint() -> str:
    """Hash of the install's top-level .py files — lets us tell whether an
    overlay actually changed any code (vs. re-pulling identical files)."""
    h = hashlib.sha256()
    d = app_dir()
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".py"))
    except OSError:
        return ""
    for name in names:
        try:
            with open(os.path.join(d, name), "rb") as fh:
                h.update(name.encode("utf-8"))
                h.update(fh.read())
        except OSError:
            pass
    return h.hexdigest()


def apply_update(target_sha: str | None = None) -> dict:
    """Download head-of-branch and overlay it onto the install.

    `target_sha` is the commit we're updating to (from the earlier check); it's
    recorded as the new baseline on success, so no second API call is needed.

    Returns {'ok': bool, 'sha': str|None, 'deps_changed': bool,
             'deps_ok': bool|None, 'message': str}. Never raises; failures are
            reported in the dict so the caller can keep running the old version.
    """
    req_before = _read(os.path.join(app_dir(), "requirements.txt"))
    tmp = tempfile.mkdtemp(prefix="cs-update-")
    try:
        zip_path = os.path.join(tmp, "src.zip")
        with _get(_ZIP_URL, DOWNLOAD_TIMEOUT, accept="*/*") as resp:
            with open(zip_path, "wb") as out:
                shutil.copyfileobj(resp, out)

        extract_dir = os.path.join(tmp, "x")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        # GitHub wraps everything in one top-level folder: <repo>-<branch>.
        entries = [os.path.join(extract_dir, e) for e in os.listdir(extract_dir)]
        roots = [e for e in entries if os.path.isdir(e)]
        if len(roots) != 1:
            return {"ok": False, "sha": None, "deps_changed": False,
                    "deps_ok": None, "message": "Unexpected archive layout."}
        src_root = roots[0]

        _overlay_tree(src_root, app_dir())

        # Did dependencies change? If so, refresh the venv before next launch.
        req_after = _read(os.path.join(app_dir(), "requirements.txt"))
        deps_changed = (req_before or "") != (req_after or "")
        deps_ok: bool | None = None
        if deps_changed:
            deps_ok = _refresh_dependencies()

        if target_sha:
            _write_sha(target_sha)
        return {"ok": True, "sha": target_sha, "deps_changed": deps_changed,
                "deps_ok": deps_ok, "message": "Updated."}
    except (URLError, HTTPError, zipfile.BadZipFile, OSError, ValueError) as exc:
        logger.warning("Update failed, keeping current version: %s", exc)
        return {"ok": False, "sha": None, "deps_changed": False,
                "deps_ok": None, "message": str(exc)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _refresh_dependencies() -> bool | None:
    """Re-install requirements into the .venv. None if there's no venv to use."""
    py = _venv_python()
    if not py:
        logger.warning("requirements.txt changed but no .venv found — "
                       "re-run install.bat to pick up new dependencies.")
        return None
    try:
        subprocess.run(
            [py, "-m", "pip", "install", "-r",
             os.path.join(app_dir(), "requirements.txt")],
            check=True, capture_output=True, text=True, timeout=600,
        )
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("Dependency refresh failed: %s", exc)
        return False


# --- GUI entry point ---------------------------------------------------------
def _busy_dialog(QtCore, QtWidgets, parent, text):
    busy = QtWidgets.QProgressDialog(text, "", 0, 0, parent)
    busy.setWindowTitle("Updating")
    busy.setCancelButton(None)
    busy.setWindowModality(QtCore.Qt.ApplicationModal)
    busy.show()
    QtWidgets.QApplication.processEvents()
    return busy


def _deps_note(result) -> str:
    if not result["deps_changed"]:
        return ""
    if result["deps_ok"] is True:
        return "\n\nNew dependencies were installed."
    if result["deps_ok"] is None:
        return ("\n\nNote: requirements changed but no .venv was found — "
                "run install.bat before starting.")
    return ("\n\nWarning: new dependencies failed to install — "
            "run install.bat before starting.")


def _offer_restart(QtWidgets, parent, short, result) -> None:
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle("Update installed")
    box.setIcon(QtWidgets.QMessageBox.Information)
    box.setText(f"Updated to {short}.{_deps_note(result)}")
    box.setInformativeText("Restart now to use the new version?")
    box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    box.setDefaultButton(QtWidgets.QMessageBox.Yes)
    if box.exec() == QtWidgets.QMessageBox.Yes:
        _relaunch()
    # If they decline, the new files are already on disk and take effect next start.


def run_update_check(parent=None) -> None:
    """Check for an update and, if newer, apply it and offer a restart.

    Call this once in launcher.main() AFTER the QApplication exists but BEFORE
    the main window is built. Safe to call unconditionally: it self-disables on
    any error and simply returns, letting the app launch as normal.
    """
    from PySide6 import QtCore, QtWidgets

    try:
        have = current_sha()
        info = latest_remote()
        if not info:
            return  # offline / rate-limited — launch the version on disk
        if have == info["sha"]:
            return  # already current

        if have is None:
            # First launch on this copy: there's no marker, and we can't tell a
            # fresh-and-current copy from a stale one without pulling. So sync to
            # the repo now, silently, and only interrupt with a restart prompt if
            # the code actually changed (a current copy pulls identical files and
            # carries on without bothering the user).
            busy = _busy_dialog(QtCore, QtWidgets, parent, "Syncing with GitHub…")
            before = _code_fingerprint()
            result = apply_update(info["sha"])
            busy.close()
            if not result["ok"] or _code_fingerprint() == before:
                return  # failed (launch current), or was already up to date
            _offer_restart(QtWidgets, parent, info["short"], result)
            return

        # We have a recorded version and we're behind it — ask before updating.
        msg = info["message"] or "(no description)"
        ask = QtWidgets.QMessageBox(parent)
        ask.setWindowTitle("Update available")
        ask.setIcon(QtWidgets.QMessageBox.Information)
        ask.setText("A newer version of Chaser's Shenanigans is available.")
        ask.setInformativeText(f"Latest commit {info['short']}: {msg}\n\nDownload and install it now?")
        ask.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        ask.setDefaultButton(QtWidgets.QMessageBox.Yes)
        if ask.exec() != QtWidgets.QMessageBox.Yes:
            return  # user declined — launch current version

        busy = _busy_dialog(QtCore, QtWidgets, parent, "Downloading update…")
        result = apply_update(info["sha"])
        busy.close()

        if not result["ok"]:
            QtWidgets.QMessageBox.warning(
                parent, "Update failed",
                "The update couldn't be completed, so the current version will "
                f"start instead.\n\nDetails: {result['message']}")
            return

        _offer_restart(QtWidgets, parent, info["short"], result)
    except Exception as exc:  # noqa: BLE001 — updater must never block launch
        logger.warning("Updater error (ignored, launching normally): %s", exc)


def _relaunch() -> None:
    """Start a fresh interpreter on the (now updated) launcher and exit this one."""
    launcher = os.path.join(app_dir(), "launcher.py")
    try:
        subprocess.Popen([sys.executable, launcher])
    except OSError as exc:
        logger.warning("Could not relaunch automatically: %s", exc)
        return
    sys.exit(0)
