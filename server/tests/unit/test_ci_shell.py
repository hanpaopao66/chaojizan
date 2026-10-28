"""GitHub Actions 里每一个 `run:` 脚本都过得了 `bash -n`(语法检查)。

撞过的:2026-10-18 给「小程序 SDK 与官方小程序」那一步加了一条检查,把 `&&` 折到了下一行开头 ——
bash 里一行以 `&&` 开头是语法错误。本地 make analyze 照样全绿(它不跑 workflow 文件),
这个错误在本地躺了九天,直到 10-27 推上去,整个「三端静态检查」job 红在这一行。

workflow 里的脚本只有 CI 自己会跑,本地没有别的地方替它把关,所以在这里用 bash 过一遍语法。
"""
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = sorted((REPO / ".github/workflows").glob("*.yml"))


def _shell(doc: dict, job: dict, step: dict) -> str:
    """这一步用什么 shell 跑:步骤自己写的 > job 的 defaults > workflow 的 defaults >
    runner 缺省(Windows 是 pwsh,其余是 bash)。只有 bash / sh 的才拿 bash -n 查"""
    for scope in (step, (job.get("defaults") or {}).get("run") or {},
                  (doc.get("defaults") or {}).get("run") or {}):
        if scope.get("shell"):
            return str(scope["shell"]).split()[0]
    return "pwsh" if "windows" in str(job.get("runs-on", "")) else "bash"


def _run_steps():
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            for i, step in enumerate(job.get("steps") or []):
                if (isinstance(step, dict) and step.get("run")
                        and _shell(doc, job, step) in ("bash", "sh")):
                    yield f"{wf.name} / {job_name} / {step.get('name') or f'第 {i + 1} 步'}", step["run"]


def test_能找到workflow里的脚本():
    """防假绿:目录挪了、文件改名了,下面那条就是在空集合上断言"""
    assert len(WORKFLOWS) >= 2
    assert sum(1 for _ in _run_steps()) >= 20


def test_每个run脚本都过得了bash语法检查(tmp_path):
    bad = []
    for where, script in _run_steps():
        f = tmp_path / "step.sh"
        f.write_text(script, encoding="utf-8")
        r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(f"{where}:{r.stderr.strip()}")
    assert not bad, "workflow 里有过不了 bash -n 的脚本:\n" + "\n".join(bad)


def test_守卫自己会红(tmp_path):
    """先造一个反例:守卫写错比没有守卫更糟(make analyze 扫美元符那次就是一直假绿)"""
    f = tmp_path / "bad.sh"
    f.write_text("(cd x && echo a\n  && echo b)\n", encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(f)], capture_output=True).returncode != 0
