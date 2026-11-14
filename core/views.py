from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from .context_processors import COOKIE_NOTICE_COOKIE_NAME, COOKIE_NOTICE_MAX_AGE


class CookiesPolicyView(TemplateView):
    """
    Página pública con el Aviso y Política de Cookies conforme a la LSSI-CE (art. 22.2),
    el RGPD y las directrices de la AEPD, detallando las cookies técnicas reales y
    la ausencia total de rastreo comercial.
    """
    template_name = 'legal/cookies_policy.html'


@require_POST
def dismiss_cookie_notice(request):
    """
    Respaldo sin JavaScript para registrar que el usuario ha leído y cerrado el aviso
    informativo de cookies mediante una cookie técnica propia.
    """
    next_url = (request.POST.get('next') or '').strip()
    fallback_url = reverse('home') if request.user.is_authenticated else reverse('users:login')

    if not next_url or not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = fallback_url

    if request.headers.get('HX-Request'):
        response = HttpResponse(status=204)
    else:
        response = redirect(next_url)

    response.set_cookie(
        key=COOKIE_NOTICE_COOKIE_NAME,
        value='1',
        max_age=COOKIE_NOTICE_MAX_AGE,
        path='/',
        samesite='Lax',
        secure=request.is_secure(),
        httponly=False,
    )
    return response
