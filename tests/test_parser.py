import unittest
from taskctl.core.parser import parse_task_md

SAMPLE_TASK_MD = """# Tasks & Roadmap

### 📌 Task [01.2]: Feature Title Here

- **Description:** Sample description
- **Systems Involved:** [core, cli]
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash-medium'
- **Status:** RUNNING

### Acceptance Criteria
- [x] First criterion met
- [ ] Second criterion pending

---

## Backlog

- [ ] **[01.3]** Next scheduled item
- [ ] **[01.4]** Future planned item

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [01.1] | Prior work | [`1234abc`] | 2026-10-01 |
"""

class TestParser(unittest.TestCase):
    def test_parse_task_md(self):
        active_task, backlog = parse_task_md(SAMPLE_TASK_MD)
        self.assertEqual(active_task["id"], "01.2")
        self.assertEqual(active_task["title"], "Feature Title Here")
        self.assertEqual(active_task["status"], "RUNNING")
        self.assertEqual(len(active_task["criteria"]), 2)
        self.assertTrue(active_task["criteria"][0]["checked"])
        self.assertFalse(active_task["criteria"][1]["checked"])

        self.assertEqual(len(backlog), 2)
        self.assertEqual(backlog[0]["id"], "01.3")
        self.assertEqual(backlog[0]["title"], "Next scheduled item")

    def test_parse_greenfield_format(self):
        greenfield_md = """# TASK.md — Current Task and Roadmap

## Active Task

### 📌 Task [XX.Y]: [Short descriptive title]

- **Description:** [2–4 lines for the agent to devise a plan.]
- **Systems Involved:** [e.g. `api-service`, `frontend`]
- **Action Type:**
  - [ ] Read-only / Documentation
  - [ ] Source code changes
- **Status:** READY FOR PLANNING

### Acceptance Criteria
- [ ] Criterion A
- [x] Criterion B

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [00.0] | Initial scaffolding (ADD greenfield) | [`0000000`] | 2026-10-01 |

---

## Backlog (Upcoming, in priority order)

- [ ] **[00.1]** [Setup stack, linters, and validation commands] — `[setup]`
- [ ] **[01.1]** [First foundation epic] — `[system]`

---

## Release / Cycle Wrap-up (Not the next task)
"""
        active_task, backlog = parse_task_md(greenfield_md)
        self.assertEqual(active_task["id"], "XX.Y")
        self.assertEqual(active_task["status"], "READY FOR PLANNING")
        self.assertEqual(len(active_task["criteria"]), 2)
        self.assertFalse(active_task["criteria"][0]["checked"])
        self.assertTrue(active_task["criteria"][1]["checked"])

        self.assertEqual(len(backlog), 2)
        self.assertEqual(backlog[0]["id"], "00.1")
        self.assertEqual(backlog[1]["id"], "01.1")

if __name__ == "__main__":
    unittest.main()
