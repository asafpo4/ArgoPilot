"""The plan example of the README is the real output of the service (spec 2.2, the North block)."""

import json
import re
from pathlib import Path

from api_support import FakeWorld, plan_url, planner_client

README = Path(__file__).resolve().parent.parent / "README.md"
PLOT_ID = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"


def readme_plan_example() -> dict:
    """The first ```json block under the heading "Plan example". Parsed, so only values count."""
    text = README.read_text()
    heading = re.search(r"^#+ Plan example\s*$", text, re.MULTILINE)
    assert heading, "the README has no heading 'Plan example'"
    block = re.search(r"```json\n(.*?)\n```", text[heading.end():], re.DOTALL)
    assert block, "no json block under 'Plan example'"
    return json.loads(block.group(1))


def test_readme_plan_example_matches_output() -> None:
    # 2026-11-17, three days, fake registry and weather (the North block of the seed data).
    with planner_client(FakeWorld()) as client:
        response = client.get(plan_url(PLOT_ID, "?days=3"))
    assert response.status_code == 200
    assert readme_plan_example() == response.json()
