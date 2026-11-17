"""Part 4: nothing is published, sent or spent without the founder's approval.

These tests are the evidence behind the "founder control" claim in the README, so they check the
failure paths (no request, pending, rejected, reused) as carefully as the happy one.
"""
import pytest

from venturegate.approval import ApprovalRejected, ApprovalRequired, Approvals
from venturegate.logger import DecisionLogger, validate_entry


@pytest.fixture
def approvals(tmp_path):
    return Approvals(tmp_path / "approvals.json", DecisionLogger(tmp_path / "log.json"))


# == blocked paths ============================================================
def test_an_action_nobody_asked_about_cannot_run(approvals):
    published = []
    with pytest.raises(ApprovalRequired, match="never put to the founder"):
        approvals.run_approved("publish_post", lambda: published.append(1),
                               agent="launch", action_name="publish")
    assert published == []


def test_a_pending_request_blocks_the_action(approvals):
    approvals.request("publish_post", kind="publish", summary="Launch post on LinkedIn")
    with pytest.raises(ApprovalRequired, match="waiting for the founder"):
        approvals.require_approval("publish_post")
    assert [item["step_id"] for item in approvals.pending()] == ["publish_post"]


def test_a_rejection_blocks_the_action_and_keeps_the_reason(approvals):
    approvals.request("publish_post", kind="publish", summary="Launch post")
    approvals.reject("publish_post", "The tone is too salesy")
    with pytest.raises(ApprovalRejected, match="salesy"):
        approvals.require_approval("publish_post")


def test_an_approval_cannot_be_used_twice(approvals):
    approvals.request("publish_post", kind="publish", summary="Launch post")
    approvals.approve("publish_post")
    done = []
    approvals.run_approved("publish_post", lambda: done.append("posted"),
                           agent="launch", action_name="publish_posts")
    with pytest.raises(ApprovalRequired, match="already used"):
        approvals.run_approved("publish_post", lambda: done.append("again"),
                               agent="launch", action_name="publish_posts")
    assert done == ["posted"]


def test_approving_one_step_does_not_approve_another(approvals):
    approvals.request("post_a", kind="publish", summary="A")
    approvals.request("post_b", kind="publish", summary="B")
    approvals.approve("post_a")
    with pytest.raises(ApprovalRequired):
        approvals.require_approval("post_b")


# == the happy path ===========================================================
def test_an_approved_action_runs_and_is_logged_as_founder(approvals):
    approvals.request("publish_post", kind="publish", summary="Launch post")
    approvals.approve("publish_post")
    result = approvals.run_approved("publish_post", lambda: "sent", agent="launch",
                                    action_name="publish_posts_MOCKED")
    assert result == "sent"
    entries = approvals.logger.read()
    for entry in entries:
        validate_entry(entry)
    assert entries[-1]["action"] == "publish_posts_MOCKED"
    assert entries[-1]["approved_by"] == "founder"
    assert any(e["action"] == "approve:publish_post" and e["approved_by"] == "founder" for e in entries)


def test_a_rejection_is_logged_without_an_approver(approvals):
    approvals.request("publish_post", kind="publish", summary="Launch post")
    approvals.reject("publish_post", "no")
    entry = approvals.logger.read()[-1]
    assert entry["action"] == "reject:publish_post" and entry["approved_by"] is None


def test_non_consuming_checks_do_not_spend_the_approval(approvals):
    """Opening the store is approved once and then checked before every simulated delivery."""
    approvals.request("open_store", kind="publish", summary="Open the mocked store")
    approvals.approve("open_store")
    for _ in range(3):
        approvals.require_approval("open_store", consume=False)
    assert approvals.status("open_store") == "approved"


# == the shape of the API =====================================================
def test_there_is_no_auto_approve_path():
    names = [name for name in dir(Approvals) if not name.startswith("_")]
    assert not [n for n in names if "auto" in n.lower() or "all" in n.lower()]


def test_an_unknown_kind_is_refused(approvals):
    with pytest.raises(ValueError):
        approvals.request("x", kind="automatic", summary="x")


def test_deciding_an_unknown_step_is_an_error(approvals):
    with pytest.raises(KeyError):
        approvals.approve("never_requested")


def test_clear_needs_a_prefix_and_never_approves(approvals):
    approvals.request("weak:step", kind="confirm", summary="x")
    approvals.request("strong:step", kind="confirm", summary="y")
    with pytest.raises(ValueError):
        approvals.clear("")
    approvals.clear("weak:")
    assert approvals.get("weak:step") is None
    assert approvals.status("strong:step") == "pending"
