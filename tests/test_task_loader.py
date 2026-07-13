from src.task_loader import load_task


def test_load_markdown_task(tmp_path):
    p = tmp_path / "t.md"
    p.write_text(
        """---
task_id: demo
goal: 测试任务
deliverables: [clean_data]
---

# 任务：测试
""",
        encoding="utf-8",
    )
    task = load_task(p)
    assert task.task_id == "demo"
    assert "clean_data" in task.deliverables
