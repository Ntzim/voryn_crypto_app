"""Transactional e-mail content (pt-BR)."""

from html import escape
from urllib.parse import quote

from app.core.config import get_settings
from app.core.email import EmailMessage


def _link(path: str, token: str) -> str:
    return f"{get_settings().frontend_url.rstrip('/')}{path}?token={quote(token)}"


def _html(title: str, body: str, cta_label: str | None = None, cta_url: str | None = None) -> str:
    button = (
        f'<p style="margin:28px 0"><a href="{cta_url}" style="background:#6366F1;color:#F8FAFC;'
        f'padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600">'
        f"{cta_label}</a></p>"
        if cta_url
        else ""
    )
    return (
        '<div style="background:#080F14;padding:32px;font-family:Inter,Arial,sans-serif">'
        '<div style="max-width:520px;margin:0 auto;background:#151D28;border-radius:12px;'
        'padding:32px;color:#F8FAFC;border:1px solid rgba(148,163,184,.14)">'
        '<p style="font-weight:700;letter-spacing:.18em;margin:0 0 24px">VORYN</p>'
        f'<h1 style="font-size:20px;margin:0 0 12px">{escape(title)}</h1>'
        f'<p style="color:#94A3B8;line-height:1.6">{escape(body)}</p>{button}'
        '<p style="color:#64748B;font-size:12px;margin-top:32px">'
        "Se você não reconhece esta ação, ignore este e-mail ou altere sua senha.</p>"
        "</div></div>"
    )


def verification_email(to: str, name: str, token: str) -> EmailMessage:
    url = _link("/verificar-email", token)
    hours = get_settings().email_verification_ttl_hours
    body = (
        f"Olá, {name}. Confirme seu e-mail para ativar sua conta. O link expira em {hours} horas."
    )
    return EmailMessage(
        to=to,
        subject="Confirme seu e-mail na Voryn",
        text=f"{body}\n\n{url}",
        html=_html("Confirme seu e-mail", body, "Confirmar e-mail", url),
    )


def existing_account_email(to: str) -> EmailMessage:
    url = f"{get_settings().frontend_url.rstrip('/')}/recuperar-senha"
    body = (
        "Alguém tentou criar uma conta Voryn com este e-mail, mas ele já está cadastrado. "
        "Se foi você, faça login ou recupere sua senha."
    )
    return EmailMessage(
        to=to,
        subject="Tentativa de cadastro na Voryn",
        text=f"{body}\n\n{url}",
        html=_html("Este e-mail já possui conta", body, "Recuperar senha", url),
    )


def password_reset_email(to: str, name: str, token: str) -> EmailMessage:
    url = _link("/redefinir-senha", token)
    minutes = get_settings().password_reset_ttl_minutes
    body = (
        f"Olá, {name}. Recebemos um pedido para redefinir sua senha. "
        f"O link expira em {minutes} minutos."
    )
    return EmailMessage(
        to=to,
        subject="Redefinição de senha da Voryn",
        text=f"{body}\n\n{url}",
        html=_html("Redefinir senha", body, "Criar nova senha", url),
    )


def security_notice_email(to: str, name: str, event: str) -> EmailMessage:
    body = f"Olá, {name}. {event}"
    return EmailMessage(
        to=to,
        subject="Alerta de segurança da Voryn",
        text=body,
        html=_html("Alerta de segurança", body),
    )
