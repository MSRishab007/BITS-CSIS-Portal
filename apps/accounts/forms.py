from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Email or username",
        max_length=254,
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Incorrect email/username or password.",
        "inactive": "This account has been deactivated. Please contact the department office.",
    }


class FirstPasswordChangeForm(PasswordChangeForm):
    """Same as Django's form, with clearer labels for a first-time change."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user.must_change_password:
            self.fields["old_password"].label = "Temporary password"
