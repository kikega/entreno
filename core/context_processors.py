from django.conf import settings
from django.contrib.messages.storage.cookie import CookieStorage

COOKIE_NOTICE_COOKIE_NAME = 'entreno_cookie_notice'
COOKIE_NOTICE_MAX_AGE = 31536000  # 1 año (365 días)


def _format_duration_es(seconds: int) -> str:
    """Convierte una duración en segundos a una descripción legible en español."""
    if seconds <= 0:
        return 'De sesión (se elimina al cerrar el navegador)'
    days, rem = divmod(seconds, 86400)
    if rem == 0:
        if days == 365:
            return '1 año (365 días)'
        if days == 364:
            return '1 año (52 semanas)'
        if days == 1:
            return '1 día'
        return f'{days} días'
    hours = seconds // 3600
    if hours >= 1:
        return '1 hora' if hours == 1 else f'{hours} horas'
    return f'{seconds} segundos'


def _format_cookie_attributes(*, http_only: bool, same_site: str | None, secure: bool, path: str = '/') -> str:
    """Resume los atributos técnicos reales configurados para cada cookie."""
    parts = [f'HttpOnly: {"Sí" if http_only else "No"}']
    if same_site:
        parts.append(f'SameSite={same_site}')
    parts.append(f'Secure: {"Sí (solo HTTPS)" if secure else "No (habilitable para HTTPS)"}')
    if path:
        parts.append(f'Path={path}')
    return ' · '.join(parts)


def get_cookie_inventory() -> list[dict]:
    """
    Inspecciona la configuración real de Django en `core/settings.py` y devuelve
    el inventario exacto de cookies utilizadas por EntrenoPro.
    """
    middleware = set(getattr(settings, 'MIDDLEWARE', []))
    inventory: list[dict] = []

    # 1. Cookie de sesión (SessionMiddleware)
    if 'django.contrib.sessions.middleware.SessionMiddleware' in middleware:
        session_age = int(getattr(settings, 'SESSION_COOKIE_AGE', 1209600))
        expire_at_close = bool(getattr(settings, 'SESSION_EXPIRE_AT_BROWSER_CLOSE', False))
        inventory.append({
            'name': getattr(settings, 'SESSION_COOKIE_NAME', 'sessionid'),
            'owner': 'Propia (EntrenoPro)',
            'category': 'Técnica / Autenticación',
            'purpose': (
                'Mantiene la sesión iniciada del usuario autenticado (deportista o entrenador) '
                'y conserva su estado de navegación dentro de la plataforma.'
            ),
            'duration': 'Al cerrar el navegador' if expire_at_close else _format_duration_es(session_age),
            'attributes': _format_cookie_attributes(
                http_only=bool(getattr(settings, 'SESSION_COOKIE_HTTPONLY', True)),
                same_site=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
                secure=bool(getattr(settings, 'SESSION_COOKIE_SECURE', False)),
                path=getattr(settings, 'SESSION_COOKIE_PATH', '/'),
            ),
        })

    # 2. Cookie de protección CSRF (CsrfViewMiddleware)
    if 'django.middleware.csrf.CsrfViewMiddleware' in middleware:
        csrf_age = getattr(settings, 'CSRF_COOKIE_AGE', 31449600)
        csrf_duration = 'De sesión' if csrf_age is None else _format_duration_es(int(csrf_age))
        inventory.append({
            'name': getattr(settings, 'CSRF_COOKIE_NAME', 'csrftoken'),
            'owner': 'Propia (EntrenoPro)',
            'category': 'Técnica / Seguridad',
            'purpose': (
                'Protege todos los formularios y acciones dinámicas (POST y HTMX) frente a ataques '
                'de falsificación de petición en sitios cruzados (CSRF).'
            ),
            'duration': csrf_duration,
            'attributes': _format_cookie_attributes(
                http_only=bool(getattr(settings, 'CSRF_COOKIE_HTTPONLY', False)),
                same_site=getattr(settings, 'CSRF_COOKIE_SAMESITE', 'Lax'),
                secure=bool(getattr(settings, 'CSRF_COOKIE_SECURE', False)),
                path=getattr(settings, 'CSRF_COOKIE_PATH', '/'),
            ),
        })

    # 3. Cookie temporal de avisos de interfaz (MessageMiddleware + CookieStorage/FallbackStorage)
    message_storage = getattr(settings, 'MESSAGE_STORAGE', 'django.contrib.messages.storage.fallback.FallbackStorage')
    if (
        'django.contrib.messages.middleware.MessageMiddleware' in middleware
        and ('CookieStorage' in message_storage or 'FallbackStorage' in message_storage)
    ):
        inventory.append({
            'name': CookieStorage.cookie_name,
            'owner': 'Propia (EntrenoPro)',
            'category': 'Técnica / Mensajes de estado',
            'purpose': (
                'Transporta temporalmente notificaciones de confirmación o error tras enviar un formulario '
                '(por ejemplo, perfil guardado o cambio de contraseña) hasta mostrarse en la siguiente pantalla.'
            ),
            'duration': 'Efímera / de sesión (se elimina automáticamente al mostrarse el aviso)',
            'attributes': 'SameSite=Lax · Path=/ · Gestionada por django.contrib.messages',
        })

    # 4. Cookie de idioma si estuviera activo LocaleMiddleware
    if 'django.middleware.locale.LocaleMiddleware' in middleware:
        lang_age = getattr(settings, 'LANGUAGE_COOKIE_AGE', None)
        inventory.append({
            'name': getattr(settings, 'LANGUAGE_COOKIE_NAME', 'django_language'),
            'owner': 'Propia (EntrenoPro)',
            'category': 'Técnica / Preferencia de idioma',
            'purpose': 'Recuerda el idioma de interfaz seleccionado por el usuario.',
            'duration': _format_duration_es(int(lang_age)) if lang_age else 'De sesión',
            'attributes': _format_cookie_attributes(
                http_only=bool(getattr(settings, 'LANGUAGE_COOKIE_HTTPONLY', False)),
                same_site=getattr(settings, 'LANGUAGE_COOKIE_SAMESITE', None),
                secure=bool(getattr(settings, 'LANGUAGE_COOKIE_SECURE', False)),
                path=getattr(settings, 'LANGUAGE_COOKIE_PATH', '/'),
            ),
        })

    # 5. Cookie técnica de confirmación de lectura de este aviso
    inventory.append({
        'name': COOKIE_NOTICE_COOKIE_NAME,
        'owner': 'Propia (EntrenoPro)',
        'category': 'Técnica / Preferencia de interfaz',
        'purpose': (
            'Se guarda únicamente si pulsas «Entendido» para recordar que ya has leído este aviso '
            'y no volver a mostrarlo de forma repetitiva. No contiene identificadores personales ni realiza rastreo.'
        ),
        'duration': _format_duration_es(COOKIE_NOTICE_MAX_AGE),
        'attributes': 'HttpOnly: No · SameSite=Lax · Path=/',
    })

    return inventory


def cookie_notice_info(request) -> dict:
    """Expone el estado del aviso informativo de cookies y el inventario técnico a todas las plantillas."""
    cookies = getattr(request, 'COOKIES', {}) or {}
    return {
        'cookie_notice_dismissed': cookies.get(COOKIE_NOTICE_COOKIE_NAME) == '1',
        'cookie_notice_cookie_name': COOKIE_NOTICE_COOKIE_NAME,
        'cookie_notice_max_age': COOKIE_NOTICE_MAX_AGE,
        'cookie_inventory': get_cookie_inventory(),
    }
