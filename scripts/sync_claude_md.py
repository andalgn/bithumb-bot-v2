"""CLAUDE.md와 실제 프로젝트 구조의 동기화를 검증/갱신하는 스크립트.

사용법:
  python scripts/sync_claude_md.py --check   # 불일치 감지 (pre-commit용)
  python scripts/sync_claude_md.py --update  # CLAUDE.md 자동 갱신
  python scripts/sync_claude_md.py --diff    # 차이점만 출력
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = ROOT / "CLAUDE.md"

# 소스 디렉토리 (스캔 대상)
SOURCE_DIRS = [
    "app", "strategy", "market", "risk", "execution",
    "backtesting", "bot_telegram", "scripts",
]

# 자동생성 마커
TREE_START = "<!-- AUTO-GENERATED-TREE: START -->"
TREE_END = "<!-- AUTO-GENERATED-TREE: END -->"

# __init__.py, __pycache__ 제외
EXCLUDE_FILES = {"__init__.py", "__pycache__"}


def scan_project_tree() -> dict[str, list[tuple[str, str]]]:
    """실제 파일 시스템에서 .py 파일 목록과 설명을 수집한다."""
    tree: dict[str, list[tuple[str, str]]] = {}

    for dir_name in SOURCE_DIRS:
        dir_path = ROOT / dir_name
        if not dir_path.is_dir():
            continue

        files: list[tuple[str, str]] = []
        for py_file in sorted(dir_path.glob("*.py")):
            if py_file.name in EXCLUDE_FILES:
                continue
            desc = _get_module_description(py_file)
            files.append((py_file.name, desc))

        if files:
            tree[dir_name] = files

    return tree


def _get_module_description(filepath: Path) -> str:
    """모듈 파일의 docstring에서 한 줄 설명을 추출한다."""
    try:
        source = filepath.read_text(encoding="utf-8")
        module = ast.parse(source)
        docstring = ast.get_docstring(module)
        if docstring:
            # 첫 줄만 사용 (마침표 또는 줄바꿈 전까지)
            first_line = docstring.split("\n")[0].strip()
            # 너무 길면 자르기
            if len(first_line) > 60:
                first_line = first_line[:57] + "..."
            return first_line
    except (SyntaxError, UnicodeDecodeError):
        pass
    return ""


def parse_claude_md_tree() -> dict[str, list[str]]:
    """CLAUDE.md의 AUTO-GENERATED 섹션에서 파일 목록을 파싱한다."""
    if not CLAUDE_MD.exists():
        return {}

    content = CLAUDE_MD.read_text(encoding="utf-8")

    # 마커 사이 내용 추출
    start_idx = content.find(TREE_START)
    end_idx = content.find(TREE_END)
    if start_idx < 0 or end_idx < 0:
        # 마커 없으면 기존 방식으로 파싱 시도
        return _parse_legacy_tree(content)

    section = content[start_idx + len(TREE_START):end_idx]

    tree: dict[str, list[str]] = {}
    current_dir = ""

    for line in section.split("\n"):
        # 디렉토리 패턴: ├── app/ 또는 │   ├── 형태가 아닌 것
        dir_match = re.search(r"[├└]── (\w+)/", line)
        if dir_match and "." not in dir_match.group(1):
            current_dir = dir_match.group(1)
            tree[current_dir] = []
            continue

        # 파일 패턴: │   ├── filename.py
        file_match = re.search(r"[├└]── ([\w.]+\.py)", line)
        if file_match and current_dir:
            tree[current_dir].append(file_match.group(1))

    return tree


def _parse_legacy_tree(content: str) -> dict[str, list[str]]:
    """마커 없는 기존 CLAUDE.md에서 프로젝트 구조를 파싱한다."""
    tree: dict[str, list[str]] = {}
    in_structure = False
    current_dir = ""

    for line in content.split("\n"):
        if "## 프로젝트 구조" in line:
            in_structure = True
            continue
        if in_structure and line.startswith("## "):
            break
        if not in_structure:
            continue

        dir_match = re.search(r"[├└]── (\w+)/", line)
        if dir_match and "." not in dir_match.group(1):
            current_dir = dir_match.group(1)
            tree[current_dir] = []
            continue

        file_match = re.search(r"[├└]── ([\w.]+\.py)", line)
        if file_match and current_dir:
            tree[current_dir].append(file_match.group(1))

    return tree


def generate_tree_section(tree: dict[str, list[tuple[str, str]]]) -> str:
    """실제 파일 트리를 마크다운으로 생성한다."""
    lines = [TREE_START, "```"]
    lines.append("bithumb_auto_v2/")
    lines.append("├── CLAUDE.md                    ← 이 파일")
    lines.append("├── research_program.md          ← 자율 연구 방향 설정")
    lines.append("├── docs/                        ← PRD 기반 설계 문서")
    lines.append("├── tasks/                       ← 단계별 작업 명세")

    dir_list = list(tree.keys())
    # 고정 순서 + 나머지
    order = [
        "app", "strategy", "market", "risk", "execution",
        "backtesting", "bot_telegram", "scripts",
    ]
    sorted_dirs = [d for d in order if d in tree]
    for extra in dir_list:
        if extra not in sorted_dirs:
            sorted_dirs.append(extra)

    for i, dir_name in enumerate(sorted_dirs):
        files = tree[dir_name]
        is_last_dir = (i == len(sorted_dirs) - 1)
        dir_prefix = "└──" if is_last_dir else "├──"
        lines.append(f"{dir_prefix} {dir_name}/")

        for j, (fname, desc) in enumerate(files):
            is_last_file = (j == len(files) - 1)
            if is_last_dir:
                file_prefix = "    └──" if is_last_file else "    ├──"
            else:
                file_prefix = "│   └──" if is_last_file else "│   ├──"

            if desc:
                # 정렬을 위해 패딩
                padded_name = fname.ljust(28)
                lines.append(f"{file_prefix} {padded_name}← {desc}")
            else:
                lines.append(f"{file_prefix} {fname}")

    # 기타 고정 항목
    lines.append("├── configs/")
    lines.append("│   └── config.yaml              ← 통합 설정")
    lines.append("├── tests/                       ← pytest 테스트")
    lines.append("├── data/                        ← 런타임 데이터 (git 무시)")
    lines.append("├── requirements.txt")
    lines.append("├── .env.example")
    lines.append("├── .gitignore")
    lines.append("└── run_bot.py                   ← 진입점")
    lines.append("```")
    lines.append(TREE_END)

    return "\n".join(lines)


def compare_trees(
    actual: dict[str, list[tuple[str, str]]],
    documented: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    """실제 파일과 문서 기재 파일을 비교한다.

    Returns:
        (missing_in_doc: 문서에 없는 실제 파일, missing_in_fs: 실제에 없는 문서 파일)
    """
    missing_in_doc: list[str] = []
    missing_in_fs: list[str] = []

    actual_flat: dict[str, set[str]] = {}
    for d, files in actual.items():
        actual_flat[d] = {f[0] for f in files}

    doc_flat: dict[str, set[str]] = {}
    for d, files in documented.items():
        # SOURCE_DIRS에 포함된 디렉토리만 비교 (configs, tests, data 등 제외)
        if d not in SOURCE_DIRS:
            continue
        doc_flat[d] = set(files)

    # 실제에 있는데 문서에 없는 파일
    for d, files in actual_flat.items():
        doc_files = doc_flat.get(d, set())
        for f in files - doc_files:
            missing_in_doc.append(f"{d}/{f}")

    # 문서에 있는데 실제에 없는 파일
    for d, files in doc_flat.items():
        actual_files = actual_flat.get(d, set())
        for f in files - actual_files:
            missing_in_fs.append(f"{d}/{f}")

    return sorted(missing_in_doc), sorted(missing_in_fs)


def update_claude_md(tree_section: str) -> None:
    """CLAUDE.md의 프로젝트 구조 섹션을 갱신한다."""
    content = CLAUDE_MD.read_text(encoding="utf-8")

    start_idx = content.find(TREE_START)
    end_idx = content.find(TREE_END)

    if start_idx >= 0 and end_idx >= 0:
        # 기존 마커 영역 교체
        new_content = (
            content[:start_idx]
            + tree_section
            + content[end_idx + len(TREE_END):]
        )
    else:
        # 마커 없으면 기존 프로젝트 구조 섹션을 찾아 교체
        pattern = r"(## 프로젝트 구조\n+)```\n.*?```"
        replacement = f"\\1{tree_section}"
        new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    CLAUDE_MD.write_text(new_content, encoding="utf-8")


def main() -> int:
    """메인 실행."""
    parser = argparse.ArgumentParser(description="CLAUDE.md 동기화 검증/갱신")
    parser.add_argument("--check", action="store_true", help="불일치 감지 (비제로 종료)")
    parser.add_argument("--update", action="store_true", help="CLAUDE.md 갱신")
    parser.add_argument("--diff", action="store_true", help="차이점만 출력")
    args = parser.parse_args()

    if not any([args.check, args.update, args.diff]):
        args.diff = True  # 기본: diff 모드

    # 실제 트리 스캔
    actual_tree = scan_project_tree()
    documented_tree = parse_claude_md_tree()
    missing_in_doc, missing_in_fs = compare_trees(actual_tree, documented_tree)

    has_issues = bool(missing_in_doc) or bool(missing_in_fs)

    if args.diff or args.check:
        if missing_in_doc:
            print(f"[!] 문서에 없는 실제 파일 ({len(missing_in_doc)}건):")
            for f in missing_in_doc:
                print(f"  + {f}")

        if missing_in_fs:
            print(f"[!] 실제에 없는 문서 파일 ({len(missing_in_fs)}건):")
            for f in missing_in_fs:
                print(f"  - {f}")

        if not has_issues:
            print("[OK] CLAUDE.md와 프로젝트 구조 동기화됨")

    if args.update:
        tree_section = generate_tree_section(actual_tree)
        update_claude_md(tree_section)
        print(f"[OK] CLAUDE.md 갱신 완료 ({sum(len(v) for v in actual_tree.values())}개 모듈)")

    if args.check and has_issues:
        print("\n자동 갱신: python scripts/sync_claude_md.py --update")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
