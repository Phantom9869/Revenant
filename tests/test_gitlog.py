from revenant.harvest.gitlog import END, SEP, commits_per_year, parse_log, pickaxe, read_commits


def test_parse_log_handles_multiline_bodies_and_merges():
    rec1 = SEP.join(["a" * 40, "p1", "Ada", "2018-03-03T10:00:00+00:00", "subject one", "line1\n\nline2"]) + END
    rec2 = SEP.join(["b" * 40, "p1 p2", "Bob", "2019-01-01T00:00:00+00:00", "Merge pull request #1", ""]) + END
    commits = parse_log(rec1 + "\n" + rec2)
    assert [c.subject for c in commits] == ["subject one", "Merge pull request #1"]
    assert commits[0].body == "line1\n\nline2"
    assert commits[0].short == "a" * 7
    assert not commits[0].is_merge and commits[1].is_merge


def test_read_commits_and_pickaxe_on_a_real_repo(gitrepo):
    gitrepo.commit({"t.py": "assert n == 191\n"}, "containing test", author="Kenneth")
    gitrepo.commit({"other.py": "x = 1\n"}, "unrelated")
    gitrepo.commit({"t.py": "assert n == 192\n"}, "Fix tests", author="Ordanis")
    commits = read_commits(gitrepo)
    assert [c.subject for c in commits] == ["containing test", "unrelated", "Fix tests"]  # oldest first
    assert commits[0].files == ["t.py"]
    assert commits_per_year(commits) == {int(commits[0].date[:4]): 3}
    added_192 = pickaxe(gitrepo, "== 192", "t.py")
    assert [c.subject for c in added_192] == ["Fix tests"]
    assert [c.author for c in pickaxe(gitrepo, "== 191", "t.py")] == ["Kenneth", "Ordanis"]
