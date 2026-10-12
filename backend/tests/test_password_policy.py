from app.services.password_policy import password_policy_errors


def test_password_policy_reports_each_missing_requirement():
    errors = password_policy_errors("")
    assert len(errors) == 5


def test_password_policy_accepts_standard_password():
    assert password_policy_errors("Correct horse battery staple!7") == []
