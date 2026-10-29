"""checks/word_budget.py: the mockup's words plus 15 %, and the verdict on measured counts."""

from __future__ import annotations

import json

from checks import word_budget


def test_budget_is_the_mockup_plus_fifteen_percent_rounded_down() -> None:
    assert word_budget.budget("overview") == 184  # 160 * 1.15
    for screen, words in word_budget.MOCKUP_WORDS.items():
        assert words <= word_budget.budget(screen) <= words * 1.15


def test_counts_within_budget_pass_and_over_budget_fail(tmp_path, capsys) -> None:
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"overview": 184, "treasury": 10}))
    assert word_budget.main([str(ok)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"overview": 185, "nowhere": 1}))
    assert word_budget.main([str(bad)]) == 1
    err = capsys.readouterr().err
    assert "overview: 185 words, budget 184" in err
    assert "nowhere: no mockup budget" in err


def test_budget_flag_prints_one_number(capsys) -> None:
    assert word_budget.main(["--budget", "execution"]) == 0
    assert capsys.readouterr().out.strip() == str(word_budget.budget("execution"))
    assert word_budget.main(["--budget", "home"]) == 2
