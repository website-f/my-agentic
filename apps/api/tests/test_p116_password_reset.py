"""P116 (feedback 19 Nov): forgot password, reset it with a 6-digit code by email."""

import re


from .test_p92_signin_mail import (  # noqa: F401
    anon,
    audit_rows,
    graph,
    login,
    sender_on,
    setup_owner,
    signed_in_member,
    user,
)

NEW = "a-brand-new-password-1"


def code_in(fake, email: str) -> str:
    html = fake.to(email)[-1]["body"]["message"]["body"]["content"]
    m = re.search(r">(\d{6})</div>", html)
    assert m, html
    return m.group(1)

