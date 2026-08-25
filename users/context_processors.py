# Agrupa las vistas que pertenecen conceptualmente a cada sección de navegación,
# para resaltar el elemento activo del menú aunque la URL actual sea interna.
SECTION_MAP = {
    'home': {'home', 'onboarding', 'become_trainer'},
    'training:athlete_dashboard': {
        'athlete_dashboard', 'live_workout', 'profile_edit',
        'log_progress', 'log_set_htmx', 'start_exercise', 'finish_exercise',
        'complete_workout',
    },
    'training:trainer_dashboard': {
        'trainer_dashboard', 'plan_create', 'plan_detail',
        'athlete_detail', 'trainer_athlete_edit', 'generate_smart_plan',
        'exercise_list', 'exercise_create', 'exercise_edit', 'exercise_delete',
    },
}


def capabilities(request):
    """
    Expone las capacidades del usuario autenticado y los elementos de navegación
    disponibles a todas las plantillas, sustituyendo al antiguo rol activo de sesión.
    """
    user = request.user

    caps = {
        'is_trainer': False,
        'is_athlete': False,
        'is_dual': False,
        'nav_items': [],
    }

    if not user.is_authenticated:
        return {'caps': caps}

    match = getattr(request, 'resolver_match', None)
    current_url_name = getattr(match, 'url_name', None) or ''

    def _is_active(url_name):
        return current_url_name in SECTION_MAP.get(url_name, {url_name})

    is_trainer = user.is_trainer
    is_athlete = user.is_athlete

    nav_items = [
        {
            'url_name': 'home',
            'label': 'Resumen',
            'icon_path': 'M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75',
            'available': True,
        },
        {
            'url_name': 'training:athlete_dashboard',
            'label': 'Mi entrenamiento',
            'icon_path': 'M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z',
            'available': is_athlete,
        },
        {
            'url_name': 'training:trainer_dashboard',
            'label': 'Mis deportistas',
            'icon_path': 'M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z',
            'available': is_trainer,
        },
        {
            'url_name': 'training:exercise_list',
            'label': 'Catálogo',
            'icon_path': 'M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12',
            'available': is_trainer,
        },
        {
            'url_name': 'users:profile_edit',
            'label': 'Mi perfil',
            'icon_path': 'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
            'available': is_athlete,
        },
    ]

    for item in nav_items:
        item['active'] = _is_active(item['url_name'])

    caps.update({
        'is_trainer': is_trainer,
        'is_athlete': is_athlete,
        'is_dual': is_trainer and is_athlete,
        'nav_items': [item for item in nav_items if item['available']],
    })

    return {'caps': caps}
