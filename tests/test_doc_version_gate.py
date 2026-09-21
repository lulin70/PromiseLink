"""③ 文档版本一致性门禁的行为测试（2026-09-21）。

被守护的契约：README 三语里**声称**的文档版本必须等于文档头部**声明**的版本
（README 是用户第一印象；曾长期停在 PRD v5.8 而文档已是 v5.9）。

反向探针内置在本文件：篡改文档头部 → 门禁必须变红；README 选择器失效 →
门禁必须变红（而不是"检查了 0 条然后绿"）。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/quality/check_doc_versions.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_doc_versions", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_doc_versions"] = module
    spec.loader.exec_module(module)
    return module


def _write_min_repo(root: pathlib.Path, prd: str = "5.9", tech: str = "3.2", readme_prd: str = "5.9") -> None:
    (root / "docs/spec").mkdir(parents=True, exist_ok=True)
    (root / "docs/architecture").mkdir(parents=True, exist_ok=True)
    (root / "docs/spec/PRD_v1.md").write_text(f"# PRD\n\n> **版本**: v{prd}\n", encoding="utf-8")
    (root / "docs/architecture/PromiseLink_技术设计_v1.md").write_text(
        f"# 技术设计\n\n> **版本**: v{tech}\n", encoding="utf-8"
    )
    (root / "README.md").write_text(
        f"| 文档版本 | PRD v{readme_prd} / Tech v{tech} |\n"
        f"- [PRD v{readme_prd}](docs/spec/PRD_v1.md) - 产品需求文档\n"
        f"- [技术设计 v{tech}](docs/architecture/PromiseLink_技术设计_v1.md) - 方案\n",
        encoding="utf-8",
    )
    (root / "README.en.md").write_text(
        f"| Documentation version | PRD v{readme_prd} / Tech v{tech} |\n"
        f"- [PRD v{readme_prd}](docs/spec/PRD_v1.md)\n"
        f"- [Technical Design v{tech}](docs/architecture/PromiseLink_技术设计_v1.md)\n",
        encoding="utf-8",
    )
    (root / "README.jp.md").write_text(
        f"| ドキュメントバージョン | PRD v{readme_prd} / Tech v{tech} |\n"
        f"- [PRD v{readme_prd}](docs/spec/PRD_v1.md)\n"
        f"- [技術設計 v{tech}](docs/architecture/PromiseLink_技术设计_v1.md)\n",
        encoding="utf-8",
    )


def test_gate_passes_on_the_real_repository(capsys: pytest.CaptureFixture[str]) -> None:
    """真实仓库当前必须一致（否则 CI 的 test job 会红）。"""
    code = _load_module().main([str(ROOT)])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "12 条版本声称" in out, out


def test_gate_ignores_milestone_lines_but_flags_the_version_row(tmp_path: pathlib.Path) -> None:
    """里程碑段里的历史版本（PRD v5.2）不算漂移；「文档版本」行必须被检查。"""
    _write_min_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\n- [x] PRD v5.2（历史里程碑，非本轮基线）\n",
        encoding="utf-8",
    )

    assert _load_module().main([str(tmp_path)]) == 0

    # 反向探针①：README 声称的版本被改旧 → 必须变红
    readme.write_text(readme.read_text(encoding="utf-8").replace("PRD v5.9 /", "PRD v5.8 /"), encoding="utf-8")
    assert _load_module().main([str(tmp_path)]) == 1


def test_gate_fails_when_document_header_moves_ahead(tmp_path: pathlib.Path) -> None:
    """反向探针②：文档升版（v9.9）而 README 未跟 → 必须变红。"""
    _write_min_repo(tmp_path, prd="9.9")

    assert _load_module().main([str(tmp_path)]) == 1


def test_gate_fails_loudly_when_no_claim_can_be_found(tmp_path: pathlib.Path) -> None:
    """反向探针③：README 被改写导致一条声称都抽不到 → 必须变红，禁止"检查 0 条然后绿"。"""
    _write_min_repo(tmp_path)
    for name in ("README.md", "README.en.md", "README.jp.md"):
        (tmp_path / name).write_text("# 什么都没有\n", encoding="utf-8")

    assert _load_module().main([str(tmp_path)]) == 1
