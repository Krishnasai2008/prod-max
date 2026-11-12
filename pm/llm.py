import os
import shlex
import signal
import subprocess

from pm.db import DEFAULTS, get_setting

TIMEOUT = 120
MAX_REPLY = 200_000


def command(conn) -> list[str] | None:
    value = get_setting(conn, "llm_cmd", DEFAULTS["llm_cmd"])
    if not value:
        return None
    try:
        words = shlex.split(value)
    except ValueError:
        words = []
    if not words or not words[0]:
        raise ValueError("llm_cmd must be a command line, like: my-llm --model small")
    words[0] = os.path.expanduser(words[0])
    return words


def available(conn) -> bool:
    try:
        return command(conn) is not None
    except ValueError:
        return False


def _run(argv, *, input, timeout, **_):
    """subprocess.run, but the command gets its own process group and the whole group is
    stopped on a timeout or Ctrl-C, so a wrapper script's child can't hold the reply open."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", start_new_session=True)
    try:
        out, err = proc.communicate(input, timeout=timeout)
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass  # already gone
        proc.communicate()
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def ask(conn, prompt: str, *, timeout: int = TIMEOUT, run=_run) -> str:
    argv = command(conn)
    if argv is None:
        raise ValueError("set llm_cmd first, like: pm set llm_cmd 'my-llm --model small'")
    try:
        proc = run(argv, input=prompt, capture_output=True, text=True,
                   errors="replace", timeout=timeout)
    except (FileNotFoundError, PermissionError):
        raise ValueError(f"llm_cmd not found: {argv[0]}") from None
    except subprocess.TimeoutExpired:
        raise ValueError(f"the llm command took over {timeout}s") from None
    except OSError as e:
        raise ValueError(f"couldn't run the llm command: {e}") from None
    if proc.returncode != 0:
        lines = [line.strip() for line in (proc.stderr or "").splitlines()]
        first = next((line for line in lines if line), "")
        message = f"the llm command failed (exit {proc.returncode})"
        raise ValueError(f"{message}: {first[:200]}" if first else message)
    reply = (proc.stdout or "").strip()
    if not reply:
        raise ValueError("the llm command printed nothing")
    return reply[:MAX_REPLY]


def fenced(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].lstrip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return text
