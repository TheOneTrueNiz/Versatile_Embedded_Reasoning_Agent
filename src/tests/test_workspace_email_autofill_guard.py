from __future__ import annotations

from api.server import _build_workspace_email_autofill_directive


def test_workspace_email_directive_for_authenticated_account() -> None:
    directive = _build_workspace_email_autofill_directive(
        "owner@example.com",
        authenticated=True,
    )
    lowered = directive.lower()
    assert "owner@example.com" in directive
    assert "do not ask for email" in lowered
    assert "authenticated" in lowered


def test_workspace_email_directive_for_onboarded_but_auth_pending() -> None:
    directive = _build_workspace_email_autofill_directive(
        "owner@example.com",
        authenticated=False,
    )
    lowered = directive.lower()
    assert "owner@example.com" in directive
    assert "auth pending" in lowered
    assert "ask for an email only if no onboarded workspace account exists" in lowered


def test_workspace_email_directive_for_unknown_account() -> None:
    directive = _build_workspace_email_autofill_directive(
        "",
        authenticated=False,
    )
    lowered = directive.lower()
    assert "no onboarded google workspace account is available" in lowered
    assert "ask for email only" in lowered
