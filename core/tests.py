from django.test import TestCase, override_settings
from django.urls import reverse

from users.models import AthleteProfile, CustomUser


class CookieNoticeAndPolicyTests(TestCase):
    """Pruebas del aviso informativo de cookies, inventario real y ausencia de rastreo comercial."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='cookies_user@entreno.pro',
            password='PasswordSegura2026!',
        )
        AthleteProfile.objects.create(user=self.user)

    def test_cookies_policy_accessible_without_login(self):
        """La política/aviso de cookies es pública y detalla las cookies reales y la ausencia de rastreo."""
        response = self.client.get(reverse('cookies_policy'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Aviso y Política de Cookies')
        self.assertContains(response, 'no utilizamos cookies ni tecnologías equivalentes para ningún tipo de rastreo comercial')
        self.assertContains(response, 'LSSI-CE')
        self.assertContains(response, 'RGPD')
        self.assertContains(response, 'AEPD')
        self.assertContains(response, 'entreno_sessionid')
        self.assertContains(response, 'entreno_csrftoken')
        self.assertContains(response, 'messages')
        self.assertContains(response, 'entreno_cookie_notice')
        self.assertContains(response, reverse('users:login'))

    def test_cookies_policy_accessible_when_authenticated(self):
        """Los usuarios autenticados pueden acceder al aviso de cookies y regresar al resumen."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('cookies_policy'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Volver al resumen')
        self.assertContains(response, 'Ver cookies utilizadas')

    def test_cookie_banner_visible_by_default_on_login_and_home(self):
        """El banner informativo de primera capa se muestra mientras no se haya confirmado su lectura."""
        login_resp = self.client.get(reverse('users:login'))
        self.assertEqual(login_resp.status_code, 200)
        self.assertContains(login_resp, 'id="cookieNoticeBanner"')
        self.assertContains(login_resp, 'No se utilizan cookies para ningún tipo de rastreo comercial')
        self.assertContains(login_resp, 'Entendido')
        self.assertContains(login_resp, 'Ver cookies utilizadas')
        self.assertContains(login_resp, reverse('cookies_policy'))

        self.client.force_login(self.user)
        home_resp = self.client.get(reverse('home'))
        self.assertEqual(home_resp.status_code, 200)
        self.assertContains(home_resp, 'id="cookieNoticeBanner"')
        self.assertContains(home_resp, reverse('cookies_policy'))

    def test_dismiss_cookie_notice_sets_technical_cookie_and_hides_banner(self):
        """Al pulsar 'Entendido' (respaldo POST), se guarda la cookie técnica y desaparece el banner."""
        login_url = reverse('users:login')
        response = self.client.post(
            reverse('dismiss_cookie_notice'),
            {'next': login_url},
        )
        self.assertRedirects(response, login_url)
        self.assertIn('entreno_cookie_notice', response.cookies)
        cookie = response.cookies['entreno_cookie_notice']
        self.assertEqual(cookie.value, '1')
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(int(cookie['max-age']), 31536000)

        # En la siguiente petición el banner ya no se renderiza, pero el enlace legal y diálogo siguen accesibles
        next_page = self.client.get(login_url)
        self.assertEqual(next_page.status_code, 200)
        self.assertNotContains(next_page, 'id="cookieNoticeBanner"')
        self.assertContains(next_page, 'id="cookieDetailsDialog"')
        self.assertContains(next_page, reverse('cookies_policy'))

    def test_dismiss_cookie_notice_rejects_external_next_url(self):
        """Evita redirecciones abiertas rechazando URLs externas en el parámetro next."""
        response = self.client.post(
            reverse('dismiss_cookie_notice'),
            {'next': 'https://evil.example.com/phishing'},
        )
        self.assertRedirects(response, reverse('users:login'))

        self.client.force_login(self.user)
        auth_response = self.client.post(
            reverse('dismiss_cookie_notice'),
            {'next': '//evil.example.com/phishing'},
        )
        self.assertRedirects(auth_response, reverse('home'))

    def test_dismiss_cookie_notice_htmx_returns_204(self):
        """Las peticiones HTMX reciben 204 No Content con la cookie técnica aplicada."""
        response = self.client.post(
            reverse('dismiss_cookie_notice'),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.cookies['entreno_cookie_notice'].value, '1')

    @override_settings(
        SESSION_COOKIE_NAME='custom_entreno_sid',
        CSRF_COOKIE_NAME='custom_entreno_csrf',
        SESSION_COOKIE_AGE=3600,
    )
    def test_cookie_inventory_reflects_django_settings_dynamically(self):
        """El inventario refleja automáticamente los nombres y duraciones reales definidos en settings.py."""
        response = self.client.get(reverse('cookies_policy'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'custom_entreno_sid')
        self.assertContains(response, 'custom_entreno_csrf')
        self.assertContains(response, '1 hora')

    def test_unique_caption_ids_between_policy_page_and_modal(self):
        """La página de cookies y el diálogo modal utilizan IDs de caption distintos para mantener DOM válido."""
        response = self.client.get(reverse('cookies_policy'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertEqual(html.count('id="cookiesPolicyTableCaption"'), 1)
        self.assertEqual(html.count('id="cookieModalTableCaption"'), 1)
