from django import template

register = template.Library()


@register.filter
def seconds_to_hms(value):
    """
    Convierte una cantidad de segundos a formato HH:MM:SS.
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        return "00:00"
    if value < 0:
        value = 0
    hours, rem = divmod(value, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


@register.filter
def extract_number(value, default=''):
    """
    Extrae el primer número de un texto (p.ej. '60kg' -> '60'). Si no hay número devuelve default.
    """
    if value is None:
        return default
    import re
    match = re.search(r'[\d]+(?:[.,]\d+)?', str(value))
    if match:
        return match.group(0)
    return default
