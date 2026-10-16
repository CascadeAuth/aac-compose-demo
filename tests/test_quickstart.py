"""The quickstart runs README steps 1 to 4 exactly as written."""
import os
import re
import shlex
import subprocess

from aac_cli._aeg.cli import parser
from conftest import REPO

# Lines of steps 1 to 4 the quickstart leaves out on purpose: the clone happens
# before it runs, the reader supplies the contact addresses, and it runs the
# reservation scenario only.
LEFT_OUT = {
    "git clone https://github.com/CascadeAuth/aac-compose-demo.git",
    "cd aac-compose-demo",
    "export VANTIS_CONTACT='you+vantis@example.com'",
    "export TOURFEDIA_CONTACT='you+tourfedia@example.com'",
    "./demo run fare-change",
    "./demo run fresh-authority",
}


def readme_step_lines():
    """Every line of the shell blocks in steps 1 to 3, and of the first block of step 4."""
    readme = (REPO / "README.md").read_text()
    steps_1_to_3 = readme.split("\n## 1. ", 1)[1].split("\n## 4. ", 1)[0]
    step_4 = readme.split("\n## 4. ", 1)[1]
    blocks = re.findall(r"```sh\n(.*?)```", steps_1_to_3, re.S) + re.findall(r"```sh\n(.*?)```", step_4, re.S)[:1]
    return [line for block in blocks for line in block.splitlines() if line.strip() and line not in LEFT_OUT]


def quickstart_step_lines():
    """The script's command lines from step 1 up to the graph, without headings, comments and trace switches."""
    script = (REPO / "quickstart").read_text()
    steps = script.split(': "== 1.', 1)[1].split(': "== View', 1)[0].splitlines()[1:]
    return [line for line in steps if line.strip() and not line.startswith((": ", "set ", "#"))]


def test_quickstart_runs_exactly_the_readme_steps():
    assert quickstart_step_lines() == readme_step_lines()


def test_quickstart_graph_command_parses_against_the_installed_aeg():
    script = (REPO / "quickstart").read_text()
    render = script.split("\naeg render ", 1)[1].split("\n\n", 1)[0].split("\nxdg-open", 1)[0]
    argv = shlex.split("aeg render " + render.replace("\\\n", ""))
    args = parser().parse_args(argv[1:])
    assert len(args.events) == 2 and len(args.actions) == 2


def test_quickstart_is_an_executable_shell_script():
    path = REPO / "quickstart"
    assert os.access(path, os.X_OK)
    subprocess.run(["bash", "-n", str(path)], check=True)
