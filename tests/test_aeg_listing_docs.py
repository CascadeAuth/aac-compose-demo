"""The public listing walkthrough parses against the installed owning CLI."""
import shlex
from pathlib import Path

from aac_cli._aeg.cli import parser
from markdown_it import MarkdownIt


def test_listing_and_selected_render_examples_use_the_released_interface():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    section = readme.split("### Discover executions and select a root", 1)[1].split("## 5.", 1)[0]
    commands = []
    for block in MarkdownIt("commonmark").parse(section):
        if block.type == "fence" and block.info == "sh":
            for line in block.content.splitlines():
                if line.startswith("aeg "):
                    argv = shlex.split(line)
                    commands.append((argv, parser().parse_args(argv[1:])))
    assert len(commands) == 6
    lists = [(argv, args) for argv, args in commands if argv[1] == "list"]
    assert {(bool(args.profile), bool(args.events or args.actions)) for _, args in lists} == {
        (False, True), (True, False), (True, True)
    }
    assert any("--from" in argv and "--to" in argv for argv, _ in lists)
    continuations = [argv for argv, _ in lists if "--page-token" in argv]
    assert len(continuations) == 1 and "--since" not in continuations[0]
    hybrid = next(argv for argv, _ in lists if "--profile" in argv and "--events" in argv)
    parser().parse_args([*hybrid[1:], "--task-ref", "attempt-1"])
    renders = [args for argv, args in commands if argv[1] == "render"]
    assert len(renders) == 1 and renders[0].root_token_id == "ROOT_ID"
    assert "control-plane" in section and "both" in section
    assert "exits 4" in section and "15 minutes" in section
    assert "archive the old" not in readme and "earlier demo" not in readme
