from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


START_DATE = date(2025, 1, 1)
END_DATE = date(2026, 12, 31)
CELL_SIZE = 10
CELL_GAP = 3
LEFT = 36
TOP = 28
ANIMATION_SECONDS = 45
BACKGROUND = "#0d1117"
COLORS = {
    "NONE": "#161b22",
    "FIRST_QUARTILE": "#0e4429",
    "SECOND_QUARTILE": "#006d32",
    "THIRD_QUARTILE": "#26a641",
    "FOURTH_QUARTILE": "#39d353",
}

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionLevel
          }
        }
      }
    }
  }
}
"""


def fetch_contributions(username: str, token: str, end_date: date) -> list[dict[str, Any]]:
    request_body = json.dumps(
        {
            "query": QUERY,
            "variables": {
                "login": username,
                "from": f"{START_DATE.isoformat()}T00:00:00Z",
                "to": f"{end_date.isoformat()}T23:59:59Z",
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=request_body,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "contribution-snake-generator",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)

    if result.get("errors"):
        messages = "; ".join(error["message"] for error in result["errors"])
        raise RuntimeError(f"GitHub GraphQL request failed: {messages}")

    user = result.get("data", {}).get("user")
    if user is None:
        raise RuntimeError(f"GitHub user {username!r} was not found")

    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [
        day
        for week in weeks
        for day in week["contributionDays"]
        if START_DATE.isoformat() <= day["date"] <= end_date.isoformat()
    ]


def build_svg(contributions: list[dict[str, Any]], end_date: date) -> str:
    first_sunday = START_DATE - timedelta(days=(START_DATE.weekday() + 1) % 7)
    last_sunday = end_date - timedelta(days=(end_date.weekday() + 1) % 7)
    week_count = (last_sunday - first_sunday).days // 7 + 1
    step = CELL_SIZE + CELL_GAP
    width = LEFT + week_count * step + CELL_GAP
    height = TOP + 7 * step + 18

    levels = {
        item["date"]: item["contributionLevel"]
        for item in contributions
    }
    dates = [
        first_sunday + timedelta(days=column * 7 + weekday)
        for column in range(week_count)
        for weekday in range(7)
    ]

    path_points: list[str] = []
    cells: list[str] = []
    keyframes: list[str] = []
    for column in range(week_count):
        weekdays = range(7) if column % 2 == 0 else range(6, -1, -1)
        for weekday in weekdays:
            index = column * 7 + weekday
            current_date = dates[index]
            x = LEFT + column * step
            y = TOP + weekday * step
            level = levels.get(current_date.isoformat(), "NONE")
            fill = COLORS.get(level, COLORS["NONE"])

            if current_date < START_DATE:
                fill = BACKGROUND

            cells.append(
                f'<rect class="cell-{index}" x="{x}" y="{y}" width="{CELL_SIZE}" '
                f'height="{CELL_SIZE}" rx="2" fill="{fill}"/>'
            )
            path_points.append(f"{x + CELL_SIZE / 2:g},{y + CELL_SIZE / 2:g}")

            eat_at = index / len(dates) * 100
            fade_at = min(eat_at + 0.15, 100)
            keyframes.append(
                f"@keyframes eat-{index}{{0%,{eat_at:.3f}%{{opacity:1}}"
                f"{fade_at:.3f}%,100%{{opacity:.16}}}}"
            )

    year_labels: list[str] = []
    for year in range(START_DATE.year, end_date.year + 1):
        year_start = date(year, 1, 1)
        column = (year_start - first_sunday).days // 7
        x = LEFT + column * step
        year_labels.append(
            f'<text x="{x}" y="16" class="year">{year}</text>'
        )

    duration = ANIMATION_SECONDS
    cell_animations = "".join(
        f".cell-{index}{{animation:eat-{index} {duration}s linear infinite}}"
        for index in range(len(dates))
    )
    path = " ".join(path_points)
    styles = "".join(keyframes) + cell_animations + f"""
      .snake{{fill:none;stroke:#58a6ff;stroke-width:5;stroke-linecap:round;
        stroke-linejoin:round;stroke-dasharray:.018 .982;
        animation:slither {duration}s linear infinite}}
      @keyframes slither{{to{{stroke-dashoffset:-1}}}}
      .year{{fill:#8b949e;font:12px sans-serif}}
      @media(prefers-reduced-motion:reduce){{.snake,rect{{animation:none!important}}}}
    """

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
      viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">
      <title id="title">Contribution snake, 2025 to {end_date.year}</title>
      <desc id="description">Contribution heatmap from January 1, 2025 through {end_date.isoformat()}.</desc>
      <style>{styles}</style>
      <rect width="100%" height="100%" fill="{BACKGROUND}"/>
      {''.join(year_labels)}
      {''.join(cells)}
      <polyline class="snake" pathLength="1" points="{path}"/>
    </svg>
    """


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    username = os.environ.get("GITHUB_USER_NAME")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to fetch contribution data")
    if not username:
        raise RuntimeError("GITHUB_USER_NAME is required to fetch contribution data")

    end_date = min(datetime.now(timezone.utc).date(), END_DATE)
    contributions = fetch_contributions(username, token, end_date)
    output = Path("dist/snake.svg")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_svg(contributions, end_date), encoding="utf-8")
    print(
        f"Generated {output} with contributions from "
        f"{START_DATE.isoformat()} through {end_date.isoformat()}."
    )


if __name__ == "__main__":
    main()
