"""Tests for check_dco — DCO Signed-off-by enforcement."""

from scripts.check_dco import check_dco, is_bot_commit


def _commit(sha="abc123", email="dev@example.com", message="feat: something"):
    return {"sha": sha, "author_email": email, "message": message}


class TestBotDetection:
    def test_github_bot_dependabot(self):
        assert is_bot_commit("dependabot[bot]@users.noreply.github.com")

    def test_github_bot_with_numeric_id(self):
        assert is_bot_commit("49699333+dependabot[bot]@users.noreply.github.com")

    def test_github_bot_actions(self):
        assert is_bot_commit("github-actions[bot]@users.noreply.github.com")

    def test_spoofed_bot_email_rejected(self):
        # Attacker sets git config email to fake [bot] — must NOT be exempt
        assert not is_bot_commit("alice[bot]@example.com")

    def test_spoofed_bot_wrong_domain_rejected(self):
        assert not is_bot_commit("bot[bot]@github.com")

    def test_human_noreply_github_not_bot(self):
        # Private GitHub email is a real human — not exempt from DCO
        assert not is_bot_commit("129645949+user@users.noreply.github.com")

    def test_github_noreply_merge_commit(self):
        # GitHub's own noreply for merge commits IS a bot
        assert is_bot_commit("noreply@github.com")

    def test_agent0_wetheagents(self):
        assert is_bot_commit("agent0@wetheagents.noreply.github.com")

    def test_agent0_system(self):
        assert is_bot_commit("agent0@system")

    def test_regular_email_not_bot(self):
        assert not is_bot_commit("cursorwea@gmail.com")

    def test_case_insensitive(self):
        assert is_bot_commit("Agent0@System")


class TestDCOCheck:
    def test_signed_commit_passes(self):
        c = _commit(message="feat: add thing\n\nSigned-off-by: Dev <dev@example.com>")
        assert check_dco([c]) == []

    def test_unsigned_commit_fails(self):
        c = _commit(message="feat: add thing")
        assert check_dco([c]) == [c]

    def test_bot_commit_exempt(self):
        c = _commit(email="agent0@wetheagents.noreply.github.com", message="Tide: 3 ops")
        assert check_dco([c]) == []

    def test_mixed_commits(self):
        signed = _commit(sha="aaa", message="feat: x\n\nSigned-off-by: A <a@b.com>")
        unsigned = _commit(sha="bbb", message="feat: y")
        bot = _commit(
            sha="ccc",
            email="github-actions[bot]@users.noreply.github.com",
            message="auto",
        )
        assert check_dco([signed, unsigned, bot]) == [unsigned]

    def test_empty_list(self):
        assert check_dco([]) == []

    def test_signoff_must_have_email(self):
        c = _commit(message="feat: x\n\nSigned-off-by: Just A Name")
        assert check_dco([c]) == [c]

    def test_signoff_in_middle_of_message(self):
        msg = "feat: x\n\nSigned-off-by: A <a@b.com>\n\nMore text after"
        c = _commit(message=msg)
        assert check_dco([c]) == []

    def test_co_authored_by_is_not_signoff(self):
        c = _commit(message="feat: x\n\nCo-Authored-By: Bot <bot@ai.com>")
        assert check_dco([c]) == [c]
