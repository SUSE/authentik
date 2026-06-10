"""email utils"""

from django.core.mail import EmailMultiAlternatives
from django.core.mail.message import sanitize_address
from django.template.exceptions import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils import translation

class TemplateEmailMessage(EmailMultiAlternatives):
    """Wrapper around EmailMultiAlternatives with integrated template rendering"""

    def __init__(
        self,
        to: list[tuple[str, str]],
        template_name=None,
        template_context=None,
        language="",
        **kwargs,
    ):
        sanitized_to = []
        # Ensure that all recipients are valid
        for recipient_name, recipient_email in to:
            # Remove any newline characters from name and email before sanitizing
            clean_name = (
                recipient_name.replace("\n", " ").replace("\r", " ") if recipient_name else ""
            )
            clean_email = (
                recipient_email.replace("\n", "").replace("\r", "") if recipient_email else ""
            )
            sanitized_to.append(sanitize_address((clean_name, clean_email), "utf-8"))
        super().__init__(to=sanitized_to, **kwargs)

        if template_context is None:
            template_context = {}

        # Field that can be populated by the attach_file template tag
        template_context["attachments"] = {}
        if not template_name:
            return
        with translation.override(language):
            html_content = render_to_string(template_name, template_context)
            try:
                text_content = render_to_string(
                    template_name.replace("html", "txt"), template_context
                )
                self.body = text_content
            except TemplateDoesNotExist:
                pass
        self.mixed_subtype = "related"
        self.attach_alternative(html_content, "text/html")
        self.template_context = template_context
