from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from training.am_macrocycle import (
    CANONICAL_AM_BLOCKS,
    SESSION_BLOCK_UI_META,
    enforce_am_accessory_rir,
    format_am_fractional_intensity,
    format_am_reps_fraction,
    format_am_series_prescription,
)
from training.analytics import is_rm_based_exercise
from users.models import TrainerProfile, AthleteProfile, AthleteProgressLog

class Exercise(models.Model):
    """
    Representa un ejercicio individual en el catálogo del sistema, incluyendo su categoría,
    patrón de movimiento biomecánico, etiquetas deportivas, creador y la taxonomía técnica
    completa del Sistema AM (bloques de sesión, candados, complejidad, ISA, régimen contráctil,
    articulación comprometida y árbol de regresiones A/B).
    """

    CATEGORY_CHOICES = [
        ('fuerza', 'Fuerza'),
        ('potencia', 'Potencia'),
        ('movilidad', 'Movilidad'),
        ('velocidad', 'Velocidad'),
        ('pliometria', 'Pliometría'),
        ('tecnica', 'Técnica'),
        ('tactica', 'Táctica'),
        ('otro', 'Otro'),
    ]

    MOVEMENT_CHOICES = [
        ('empuje_horizontal', 'Empuje Horizontal (Banca, Flexiones)'),
        ('empuje_vertical', 'Empuje Vertical (Press Militar)'),
        ('traccion_horizontal', 'Tracción Horizontal (Remo)'),
        ('traccion_vertical', 'Tracción Vertical (Dominadas)'),
        ('dominante_cadera', 'Dominante de Cadera (Peso Muerto, Hip Thrust)'),
        ('dominante_rodilla', 'Dominante de Rodilla (Sentadilla, Zancadas)'),
        ('potencia_olimpica', 'Potencia Olímpica (Snatch, Clean, Jerk)'),
        ('metabolico', 'Condición Metabólica (Sled, Carrera, Ergómetro)'),
        ('isometria_agarre', 'Agarre / Tracción Específica (BJJ/MMA Grip)'),
        ('core_rotacional', 'Core / Anti-Rotación (Landmine, Paloff)'),
        ('otro', 'Otro'),
    ]

    # --- Taxonomía Sistema AM (BD_Maestra_Ejercicios) ---
    SESSION_BLOCK_CHOICES = [
        ('B1_Movilidad', 'B1 - Movilidad'),
        ('B2_Velocidad', 'B2 - Velocidad'),
        ('B3_Potencia', 'B3 - Potencia'),
        ('B4_Principal', 'B4 - Fuerza Principal'),
        ('B4_Accesorio', 'B4 - Fuerza Accesorio'),
        ('B4_Auxiliar', 'B4 - Fuerza Auxiliar'),
        ('B5_Cardio', 'B5 - Sistemas Energéticos (Cardio)'),
    ]

    PATRON_VECTOR_CHOICES = [
        ('Dominante_Rodilla', 'Dominante de Rodilla'),
        ('Dominante_Cadera', 'Dominante de Cadera'),
        ('Triple_Extension', 'Triple Extensión'),
        ('Empuje_Horizontal', 'Empuje Horizontal'),
        ('Empuje_Vertical', 'Empuje Vertical'),
        ('Traccion_Vertical', 'Tracción Vertical'),
        ('Traccion_Horizontal', 'Tracción Horizontal'),
        ('Rotacional_Core', 'Rotacional de Core'),
        ('Anti_Movimiento_Core', 'Anti-Movimiento de Core'),
        ('Ninguno', 'Ninguno / General'),
    ]

    LOCK_ROUTE_CHOICES = [
        ('Candado_Olimpico_R1', 'Candado Olímpico (Ruta 1)'),
        ('Ruta_Landmine_R2', 'Ruta Landmine (Ruta 2)'),
        ('Ruta_Salto_Lastrado_R3', 'Ruta Salto Lastrado (Ruta 3)'),
        ('Ruta_Balistica_Sup_R4', 'Ruta Balística Superior (Ruta 4)'),
        ('Candado_Balon_Ligero', 'Candado Balón Ligero (<= 6 kg)'),
        ('Candado_Sprint_Suelo', 'Candado Sprint en Suelo'),
        ('Libre', 'Libre (Sin candado)'),
    ]

    COMPLEXITY_LEVEL_CHOICES = [
        ('Nivel_0_Novato', 'Nivel 0 - Novato (Edad Entrenamiento = 0)'),
        ('Nivel_1_Base', 'Nivel 1 - Base'),
        ('Nivel_2_Intermedio', 'Nivel 2 - Intermedio'),
        ('Nivel_3_Avanzado', 'Nivel 3 - Avanzado'),
    ]

    ISA_TAG_CHOICES = [
        ('ISA_Estrecho', 'ISA Estrecho (< 85º - Elástico)'),
        ('ISA_Ancho', 'ISA Ancho (> 95º - Muscular)'),
        ('Universal', 'Universal (Neutro / Todos)'),
    ]

    CONTRACTILE_REGIME_CHOICES = [
        ('Dinamico_Estandar', 'Dinámico Estándar'),
        ('Concentrico_Propulsivo', 'Concéntrico Propulsivo'),
        ('High_Braking', 'High Braking (Frenado Alto)'),
        ('Fast_Braking', 'Fast Braking (Frenado Rápido)'),
        ('Isopush', 'Isopush (Isometría de Superación)'),
        ('Isohold', 'Isohold (Isometría de Mantenimiento)'),
        ('Oscilatorio', 'Oscilatorio'),
    ]

    COMPROMISED_JOINT_CHOICES = [
        ('Hombros', 'Hombros'),
        ('Lumbares', 'Lumbares'),
        ('Rodillas', 'Rodillas'),
        ('Munecas', 'Muñecas'),
        ('Tobillos', 'Tobillos'),
        ('Cuello', 'Cuello'),
        ('Codos', 'Codos'),
        ('Cadera', 'Cadera'),
        ('Ninguna', 'Ninguna'),
    ]

    AM_CANONICAL_EQUIPMENT = [
        'Barra olímpica (20 kg) y discos',
        'Rack',
        'Banco plano/inclinado',
        'Mancuernas',
        'Kettlebells',
        'Barra de dominadas',
        'Landmine',
        'Trap Bar',
        'Cajón pliométrico',
        'Balones medicinales LIGEROS (<= 6 kg)',
        'Bandas elásticas',
        'Polea / Cable',
        'Trineo (Sled)',
        'AirBike',
        'Remo Ergómetro',
        'Assault Runner / Cinta',
    ]

    code = models.CharField(
        _('código AM'),
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Código alfanumérico único en BD_Maestra_Ejercicios (ej. B1_001, B3_004, B4P_001).'),
    )
    name = models.CharField(_('nombre'), max_length=200)
    category = models.CharField(_('categoría'), max_length=50, choices=CATEGORY_CHOICES, default='otro')
    movement_pattern = models.CharField(_('patrón de movimiento'), max_length=50, choices=MOVEMENT_CHOICES, default='otro')
    sport_tags = models.JSONField(_('etiquetas de deportes'), default=list, blank=True)
    description = models.TextField(_('descripción'), blank=True)
    video_url = models.URLField(_('enlace de video'), blank=True, null=True)

    # Campos técnicos del Sistema AM
    session_block = models.CharField(
        _('bloque asignado'),
        max_length=30,
        choices=SESSION_BLOCK_CHOICES,
        blank=True,
        default='',
        db_index=True,
    )
    patron_vector = models.CharField(
        _('patrón / vector biomecánico'),
        max_length=40,
        choices=PATRON_VECTOR_CHOICES,
        blank=True,
        default='',
    )
    lock_route = models.CharField(
        _('ruta / candado algorítmico'),
        max_length=40,
        choices=LOCK_ROUTE_CHOICES,
        blank=True,
        default='',
    )
    complexity_level = models.CharField(
        _('nivel de complejidad'),
        max_length=30,
        choices=COMPLEXITY_LEVEL_CHOICES,
        blank=True,
        default='',
    )
    required_equipment = models.JSONField(
        _('material requerido'),
        default=list,
        blank=True,
        help_text=_('Lista de etiquetas de material requeridas (sincronizadas con el checklist del atleta).'),
    )
    isa_tag = models.CharField(
        _('etiqueta ISA'),
        max_length=20,
        choices=ISA_TAG_CHOICES,
        blank=True,
        default='',
    )
    contractile_regime = models.CharField(
        _('régimen contráctil'),
        max_length=30,
        choices=CONTRACTILE_REGIME_CHOICES,
        blank=True,
        default='',
    )
    compromised_joint = models.CharField(
        _('articulación comprometida'),
        max_length=20,
        choices=COMPROMISED_JOINT_CHOICES,
        blank=True,
        default='',
    )

    # Árbol de regresión articular del Sistema AM (Opción A Isométrica y Opción B Vector)
    regression_option_a = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='isometric_for_exercises',
        verbose_name=_('opción A (regresión isométrica)'),
    )
    option_a_video_url = models.URLField(
        _('enlace video opción A'),
        blank=True,
        null=True,
    )
    regression_option_b = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vector_alt_for_exercises',
        verbose_name=_('opción B (cambio de vector)'),
    )
    option_b_video_url = models.URLField(
        _('enlace video opción B'),
        blank=True,
        null=True,
    )

    created_by = models.ForeignKey(TrainerProfile, on_delete=models.CASCADE, null=True, blank=True, related_name='created_exercises', verbose_name=_('creado por'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('ejercicio')
        verbose_name_plural = _('ejercicios')

    def clean(self):
        super().clean()
        if isinstance(self.code, str):
            self.code = self.code.strip() or None
        errors = {}
        if self.pk:
            if self.regression_option_a_id == self.pk:
                errors['regression_option_a'] = _('Un ejercicio no puede ser regresión isométrica de sí mismo.')
            if self.regression_option_b_id == self.pk:
                errors['regression_option_b'] = _('Un ejercicio no puede ser alternativa de vector de sí mismo.')
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if isinstance(self.code, str):
            self.code = self.code.strip() or None
        super().save(*args, **kwargs)

    @property
    def is_am_catalog(self) -> bool:
        """Indica si el ejercicio pertenece o está parametrizado bajo el Sistema AM."""
        return bool(self.code or self.session_block)

    @property
    def effective_option_a_video_url(self):
        """Devuelve el enlace de vídeo de la Opción A (propio de la relación o heredado del ejercicio destino)."""
        if self.option_a_video_url:
            return self.option_a_video_url
        if self.regression_option_a_id and self.regression_option_a:
            return self.regression_option_a.video_url
        return None

    @property
    def effective_option_b_video_url(self):
        """Devuelve el enlace de vídeo de la Opción B (propio de la relación o heredado del ejercicio destino)."""
        if self.option_b_video_url:
            return self.option_b_video_url
        if self.regression_option_b_id and self.regression_option_b:
            return self.regression_option_b.video_url
        return None

    @property
    def required_equipment_display(self) -> str:
        """Representación legible de los materiales requeridos por el ejercicio."""
        if not self.required_equipment:
            return 'Sin material / Peso corporal'
        return ', '.join(str(item) for item in self.required_equipment)

    def __str__(self):
        """Devuelve el nombre representativo del ejercicio (precedido por su código AM si existe)."""
        if self.code:
            return f"[{self.code}] {self.name}"
        return self.name


class ExerciseDisciplineFit(models.Model):
    """
    Encaje entre un ejercicio y una disciplina deportiva. Permite evaluar del
    1 al FIT_CHOICES qué tipo de ejercicio encaja mejor en cada deporte, de
    modo que el generador pueda ampliar las recomendaciones más allá de una
    lista cerrada de ejercicios.
    """
    FIT_CHOICES = [
        (1, _('Ajuste bajo')),
        (2, _('Ajuste medio-bajo')),
        (3, _('Ajuste medio')),
        (4, _('Ajuste alto')),
        (5, _('Ajuste máximo')),
    ]

    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='discipline_fits', verbose_name=_('ejercicio'))
    sport = models.CharField(_('deporte'), max_length=50, choices=AthleteProfile.SPORT_CHOICES)
    fit = models.PositiveSmallIntegerField(_('ajuste (1-5)'), choices=FIT_CHOICES, default=3)

    class Meta:
        verbose_name = _('encaje ejercicio-deporte')
        verbose_name_plural = _('encajes ejercicio-deporte')
        unique_together = ('exercise', 'sport')
        ordering = ['-fit', 'exercise']

    def __str__(self):
        return f"{self.exercise.name} → {self.get_sport_display()} (fit {self.fit})"


class DisciplineTemplate(models.Model):
    """
    Plantilla de plan por disciplina. El sistema provee plantillas globales
    (is_default=True, created_by=None); un entrenador puede 'copiarlas' y
    editarlas a su cuenta para tener su propia versión sin pisar a otros.
    """
    name = models.CharField(_('nombre'), max_length=200)
    sport = models.CharField(_('deporte'), max_length=50, choices=AthleteProfile.SPORT_CHOICES)
    focus = models.CharField(_('foco'), max_length=200, blank=True)
    is_default = models.BooleanField(_('plantilla del sistema'), default=False)
    is_active = models.BooleanField(_('activa'), default=True)
    created_by = models.ForeignKey(TrainerProfile, on_delete=models.CASCADE, null=True, blank=True, related_name='discipline_templates', verbose_name=_('creada por'))
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='copies', verbose_name=_('plantilla origen'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('plantilla por disciplina')
        verbose_name_plural = _('plantillas por disciplina')
        ordering = ['sport', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_sport_display()})"


class TemplateExercise(models.Model):
    """
    Ejercicio prescrito dentro de una plantilla por disciplina. Referencia al
    catálogo real de Exercises, de modo que un ejercicio puede reutilizarse en
    varias disciplinas y el generador puede sugerir más desde el catálogo.
    """
    template = models.ForeignKey(DisciplineTemplate, on_delete=models.CASCADE, related_name='items', verbose_name=_('plantilla'))
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='template_slots', verbose_name=_('ejercicio'))
    order = models.PositiveIntegerField(_('orden'), default=0)
    sets = models.CharField(_('series'), max_length=50, blank=True)
    reps = models.CharField(_('repeticiones'), max_length=50, blank=True)
    load = models.CharField(_('carga'), max_length=50, blank=True)
    rpe = models.CharField(_('RPE'), max_length=50, blank=True)
    rest = models.CharField(_('descanso'), max_length=50, blank=True)
    notes = models.TextField(_('indicaciones'), blank=True)

    class Meta:
        verbose_name = _('ejercicio de plantilla')
        verbose_name_plural = _('ejercicios de plantilla')
        ordering = ['template', 'order']

    def __str__(self):
        return f"{self.exercise.name} ({self.template})"


class Macrocycle(models.Model):
    """
    Contenedor superior de planificación del Sistema AM (V2.1) estructurado en 4 bloques
    progresivos oficiales (Off-Season, Pre-Training Camp, Training Camp y Fight Week).
    Prohíbe el uso de nomenclatura ATR y aísla los bloques en borrador hasta que el
    entrenador activa su publicación progresiva en `Panel_Control`.
    """

    name = models.CharField(
        _('nombre del macrociclo'),
        max_length=200,
        default='Macrociclo Sistema AM',
    )
    trainer = models.ForeignKey(
        TrainerProfile,
        on_delete=models.CASCADE,
        related_name='created_macrocycles',
        verbose_name=_('entrenador'),
    )
    athlete = models.ForeignKey(
        AthleteProfile,
        on_delete=models.CASCADE,
        related_name='macrocycles',
        verbose_name=_('deportista'),
    )
    target_fight_date = models.DateField(
        _('fecha objetivo de combate'),
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(_('macrociclo activo'), default=True)
    notes = models.TextField(_('notas privadas del macrociclo'), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('macrociclo')
        verbose_name_plural = _('macrociclos')
        ordering = ['-is_active', '-created_at']

    def initialize_four_blocks(self, weeks_per_block: int = 4, sessions_per_week: int = 3) -> list['MacrocycleBlock']:
        """
        Inicializa de forma idempotente los 4 bloques competitivos oficiales del Sistema AM
        (Off-Season, Pre-Training Camp, Training Camp y Fight Week) con `is_published=False`.
        """
        created_or_existing: list[MacrocycleBlock] = []
        for spec in CANONICAL_AM_BLOCKS:
            block, _ = MacrocycleBlock.objects.get_or_create(
                macrocycle=self,
                block_number=spec['block_number'],
                defaults={
                    'phase_type': spec['phase_type'],
                    'subphase': spec['subphase'],
                    'title': spec['title'],
                    'weeks_count': weeks_per_block,
                    'sessions_per_week': sessions_per_week,
                    'is_published': False,
                },
            )
            created_or_existing.append(block)
        return created_or_existing

    @property
    def published_blocks(self):
        return self.blocks.filter(is_published=True).order_by('block_number')

    @property
    def active_published_block(self) -> 'MacrocycleBlock | None':
        """
        Devuelve el bloque publicado activo que se proyecta por defecto en `Entrenamiento_Activo`.
        Prioriza el bloque publicado más reciente con sesiones pendientes; si todos están completos
        o vacíos, devuelve el de mayor `block_number` publicado.
        """
        pub = list(self.published_blocks.prefetch_related('workout_plans'))
        if not pub:
            return None
        for block in reversed(pub):
            plans = list(block.workout_plans.all())
            if not plans or any(not p.is_completed for p in plans):
                return block
        return pub[-1]

    def __str__(self):
        return f"{self.name} — {self.athlete.user.email}"


class MacrocycleBlock(models.Model):
    """
    Bloque individual (Mesociclo de 4 semanas por defecto) dentro de un Macrociclo Sistema AM.
    Controla mediante `is_published` la proyección progresiva hacia `Entrenamiento_Activo` del atleta.
    """

    PHASE_CHOICES = [
        ('off_season', 'Off-Season (> 12 sem o sin fecha)'),
        ('pre_camp', 'Pre-Training Camp (8 a 12 sem)'),
        ('training_camp', 'Training Camp (1 a 7 sem)'),
        ('fight_week', 'Fight Week (< 1 sem)'),
    ]

    SUBPHASE_CHOICES = [
        ('none', 'Estándar'),
        ('base', 'Fase Base (> 4 sem)'),
        ('tapering', 'Tapering / Puesta a Punto (≤ 4 sem)'),
    ]

    macrocycle = models.ForeignKey(
        Macrocycle,
        on_delete=models.CASCADE,
        related_name='blocks',
        verbose_name=_('macrociclo'),
    )
    block_number = models.PositiveSmallIntegerField(
        _('número de bloque (1-4)'),
        default=1,
    )
    phase_type = models.CharField(
        _('fase competitiva Sistema AM'),
        max_length=25,
        choices=PHASE_CHOICES,
        default='off_season',
    )
    subphase = models.CharField(
        _('subfase'),
        max_length=20,
        choices=SUBPHASE_CHOICES,
        default='none',
    )
    title = models.CharField(_('título del bloque'), max_length=150)
    weeks_count = models.PositiveSmallIntegerField(
        _('semanas del bloque'),
        default=4,
    )
    sessions_per_week = models.PositiveSmallIntegerField(
        _('días de sesión por semana'),
        default=3,
    )
    start_date = models.DateField(_('fecha de inicio'), null=True, blank=True)
    end_date = models.DateField(_('fecha de fin'), null=True, blank=True)
    is_published = models.BooleanField(
        _('publicar bloque en Entrenamiento Activo'),
        default=False,
    )
    published_at = models.DateTimeField(_('fecha de publicación'), null=True, blank=True)
    trainer_notes = models.TextField(
        _('notas privadas de auditoría del bloque'),
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('bloque de macrociclo')
        verbose_name_plural = _('bloques de macrociclo')
        ordering = ['macrocycle', 'block_number']
        constraints = [
            models.UniqueConstraint(
                fields=['macrocycle', 'block_number'],
                name='unique_block_number_per_macrocycle',
            ),
        ]

    def clean(self):
        super().clean()
        if self.block_number < 1 or self.block_number > 4:
            raise ValidationError({'block_number': _('El macrociclo del Sistema AM consta exactamente de los bloques 1 a 4.')})
        if self.weeks_count < 1 or self.weeks_count > 6:
            raise ValidationError({'weeks_count': _('Cada bloque debe tener entre 1 y 6 semanas.')})
        if self.sessions_per_week < 1 or self.sessions_per_week > 6:
            raise ValidationError({'sessions_per_week': _('Las sesiones semanales deben estar entre 1 y 6 días.')})

    @property
    def week_numbers(self) -> list[int]:
        return list(range(1, max(1, int(self.weeks_count or 4)) + 1))

    @property
    def day_numbers(self) -> list[int]:
        return list(range(1, max(1, int(self.sessions_per_week or 3)) + 1))

    def set_published(self, publish: bool) -> None:
        self.is_published = bool(publish)
        self.published_at = timezone.now() if self.is_published else None
        self.save(update_fields=['is_published', 'published_at', 'updated_at'])

    @property
    def has_logged_history(self) -> bool:
        """Indica si el atleta ya ha completado sesiones o registrado series reales en este bloque."""
        if self.workout_plans.filter(is_completed=True).exists():
            return True
        return LoggedSet.objects.filter(
            logged_exercise__workout_session__workout_plan__macrocycle_block=self
        ).exists()

    def clear_unlogged_future_weeks(self, from_week: int = 1) -> dict[str, int]:
        """
        Salvaguarda de Recálculo No Destructivo (Flujo B / Módulo 8):
        Elimina únicamente los planes de semanas >= `from_week` que NO estén completados y NO
        contengan series reales (`LoggedSet`), blindando al 100 % el historial de cargas del luchador.
        """
        deleted_count = 0
        preserved_count = 0
        candidates = self.workout_plans.filter(week_number__gte=from_week)
        for plan in candidates:
            if plan.has_logged_activity:
                preserved_count += 1
            else:
                plan.delete()
                deleted_count += 1
        return {'deleted': deleted_count, 'preserved': preserved_count}

    def __str__(self):
        status = 'Publicado' if self.is_published else 'Borrador'
        return f"{self.title} ({status}) — {self.macrocycle.athlete.user.email}"


class WorkoutPlan(models.Model):
    """
    Plan de entrenamiento prescriptivo asignado por un entrenador a un deportista
    para una fecha u objetivo específico, o integrado en una semana/día de un `MacrocycleBlock`.
    """

    name = models.CharField(_('nombre del plan'), max_length=200, blank=True)
    trainer = models.ForeignKey(TrainerProfile, on_delete=models.CASCADE, related_name='created_plans', verbose_name=_('entrenador'))
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name='assigned_plans', verbose_name=_('deportista'))
    macrocycle_block = models.ForeignKey(
        MacrocycleBlock,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='workout_plans',
        verbose_name=_('bloque del macrociclo'),
    )
    week_number = models.PositiveSmallIntegerField(_('semana del bloque (1-6)'), null=True, blank=True)
    day_number = models.PositiveSmallIntegerField(_('día de sesión semanal (1-6)'), null=True, blank=True)
    sport = models.CharField(_('deporte en enfoque'), max_length=50, choices=AthleteProfile.SPORT_CHOICES, default='otro')
    target_date = models.DateField(_('fecha programada'))
    is_completed = models.BooleanField(_('completado'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('plan de entrenamiento')
        verbose_name_plural = _('planes de entrenamiento')

    @staticmethod
    def visible_to_athlete_q() -> models.Q:
        """Filtro ORM que oculta al deportista cualquier sesión perteneciente a un bloque no publicado."""
        return models.Q(macrocycle_block__isnull=True) | models.Q(macrocycle_block__is_published=True)

    @property
    def is_visible_to_athlete(self) -> bool:
        if self.macrocycle_block_id is None:
            return True
        return bool(self.macrocycle_block.is_published)

    @property
    def has_logged_activity(self) -> bool:
        """True si el plan está completado o tiene al menos una serie real (`LoggedSet`) registrada."""
        if self.is_completed:
            return True
        return LoggedSet.objects.filter(
            logged_exercise__workout_session__workout_plan=self
        ).exists()

    def __str__(self):
        """Devuelve una cadena descriptiva con el nombre del plan, email del deportista y fecha programada."""
        return f"{self.name or 'Plan'} - {self.athlete.user.email} ({self.target_date})"


class PlannedExercise(models.Model):
    """
    Ejercicio prescrito dentro de un plan de entrenamiento concreto, especificando bloque concurrente
    (B1 a B5), orden, series, repeticiones, carga objetivo, RPE, RIR, tempo y descanso.
    """

    workout_plan = models.ForeignKey(WorkoutPlan, on_delete=models.CASCADE, related_name='planned_exercises', verbose_name=_('plan de entrenamiento'))
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='planned_in', verbose_name=_('ejercicio'))
    session_block = models.CharField(
        _('bloque de sesión (B1-B5)'),
        max_length=20,
        choices=Exercise.SESSION_BLOCK_CHOICES,
        blank=True,
        default='',
    )
    order = models.PositiveIntegerField(_('orden'), default=0)
    sets = models.CharField(_('series'), max_length=50, blank=True)
    reps = models.CharField(_('repeticiones'), max_length=50, blank=True)
    load = models.CharField(_('carga'), max_length=50, blank=True)
    rpe = models.CharField(_('RPE'), max_length=50, blank=True)
    rir = models.CharField(_('RIR'), max_length=50, blank=True)
    tempo = models.CharField(_('tempo'), max_length=50, blank=True)
    focus = models.CharField(_('foco'), max_length=100, blank=True)
    rest = models.CharField(_('descanso'), max_length=50, blank=True)
    notes = models.TextField(_('indicaciones'), blank=True)

    class Meta:
        verbose_name = _('ejercicio planificado')
        verbose_name_plural = _('ejercicios planificados')
        ordering = ['order']

    @property
    def effective_session_block(self) -> str:
        if self.session_block:
            return self.session_block
        if self.exercise_id and self.exercise.session_block:
            return self.exercise.session_block
        return ''

    @property
    def session_block_short(self) -> str:
        meta = SESSION_BLOCK_UI_META.get(self.effective_session_block)
        return meta['short'] if meta else ''

    @property
    def session_block_badge_class(self) -> str:
        meta = SESSION_BLOCK_UI_META.get(self.effective_session_block, SESSION_BLOCK_UI_META[''])
        return meta['badge_class']

    def _resolve_athlete_body_comp_goal(self) -> str:
        if not self.workout_plan_id:
            return ''
        athlete = getattr(self.workout_plan, 'athlete', None)
        if athlete is None:
            return ''
        try:
            triage = athlete.mma_triage
        except MMATriageProfile.DoesNotExist:
            triage = None
        return triage.body_composition_goal if triage else ''

    @property
    def am_reps_fraction(self) -> str:
        """Devuelve `Reps_Objetivo(Reps_Totales_Posibles)`, p.ej. `3(6)`."""
        rir_eff, _ = enforce_am_accessory_rir(
            self.reps,
            self.rir,
            self.rpe,
            self.effective_session_block,
            self._resolve_athlete_body_comp_goal(),
        )
        return format_am_reps_fraction(self.reps, rir_eff)

    @property
    def am_fractional_intensity(self) -> str:
        """
        Devuelve la Nomenclatura Fraccionada de Intensidad del Sistema AM:
        `Reps_Objetivo(Reps_Totales_Posibles) @ RPE X` (ej. `3(6) @ RPE 7`, `5(9) @ RPE 6`).
        """
        rir_eff, rpe_eff = enforce_am_accessory_rir(
            self.reps,
            self.rir,
            self.rpe,
            self.effective_session_block,
            self._resolve_athlete_body_comp_goal(),
        )
        return format_am_fractional_intensity(self.reps, rir_eff, rpe_eff)

    @property
    def am_series_prescription(self) -> str:
        """Devuelve la cabecera matricial completa, p.ej. `3 Series x 3(5) @ RPE 8`."""
        rir_eff, rpe_eff = enforce_am_accessory_rir(
            self.reps,
            self.rir,
            self.rpe,
            self.effective_session_block,
            self._resolve_athlete_body_comp_goal(),
        )
        return format_am_series_prescription(self.sets, self.reps, rir_eff, rpe_eff)

    def save(self, *args, **kwargs):
        if not self.session_block and self.exercise_id and self.exercise.session_block:
            self.session_block = self.exercise.session_block

        body_goal = self._resolve_athlete_body_comp_goal()
        if body_goal:
            self.rir, self.rpe = enforce_am_accessory_rir(
                self.reps,
                self.rir,
                self.rpe,
                self.effective_session_block,
                body_goal,
            )
        super().save(*args, **kwargs)

    def __str__(self):
        """Devuelve el nombre del ejercicio y el plan de entrenamiento al que pertenece."""
        return f"{self.exercise.name} ({self.workout_plan})"


class WorkoutSession(models.Model):
    """
    Registro real de una sesión de entrenamiento completada por el deportista,
    almacenando duración, calorías, frecuencia cardíaca media, RPE global,
    nivel del Semáforo de Disposición Diaria (1 a 5) y notas.
    """

    READINESS_CHOICES = [
        (5, 'Nivel 5 (Verde) — Disposición Óptima · Esquema Normal'),
        (4, 'Nivel 4 (Verde) — Buena Disposición · Esquema Normal'),
        (3, 'Nivel 3 (Verde) — Disposición Media · Esquema Normal'),
        (2, 'Nivel 2 (Amarillo) — Fatiga Moderada · Esquema Fatiga'),
        (1, 'Nivel 1 (Rojo) — Colapso Sistémico · Esquema Regenerativo'),
    ]

    workout_plan = models.OneToOneField(WorkoutPlan, on_delete=models.CASCADE, related_name='session', verbose_name=_('plan de entrenamiento'))
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name='sessions', verbose_name=_('deportista'))
    readiness_level = models.PositiveSmallIntegerField(
        _('semáforo de disposición diaria (1-5)'),
        choices=READINESS_CHOICES,
        default=4,
        help_text=_('Preconfigurado en Nivel 4 (Verde). Nivel 2 activa Esquema_Fatiga y Nivel 1 activa Colapso Sistémico.'),
    )
    date_completed = models.DateTimeField(_('fecha completado'), auto_now_add=True)
    started_at = models.DateTimeField(_('hora de inicio'), null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(_('duración (minutos)'), null=True, blank=True)
    calories_burned = models.PositiveIntegerField(_('calorías consumidas'), null=True, blank=True)
    avg_heart_rate = models.PositiveIntegerField(_('frecuencia cardíaca media'), null=True, blank=True)
    session_rpe = models.DecimalField(_('RPE global de la sesión (1-10)'), max_digits=3, decimal_places=1, null=True, blank=True)
    notes = models.TextField(_('notas del deportista'), blank=True)

    class Meta:
        verbose_name = _('sesión de entrenamiento')
        verbose_name_plural = _('sesiones de entrenamiento')

    @property
    def readiness_scheme(self) -> str:
        """Devuelve el esquema fisiológico activo según el Semáforo de Disposición (§4.2)."""
        lvl = int(self.readiness_level or 4)
        if lvl <= 1:
            return 'Esquema_Regenerativo'
        if lvl == 2:
            return 'Esquema_Fatiga'
        return 'Esquema_Normal'

    @property
    def readiness_ui_meta(self) -> dict[str, str]:
        """Metadatos visuales y mensaje clínico del Semáforo de Disposición (1 a 5)."""
        scheme = self.readiness_scheme
        if scheme == 'Esquema_Regenerativo':
            return {
                'scheme': 'Esquema Regenerativo (Colapso Sistémico)',
                'badge': '🔴 Nivel 1 · Esquema Regenerativo',
                'color': 'rose',
                'badge_class': 'bg-rose-100 text-rose-900 border-rose-300',
                'banner_class': 'bg-rose-50 border-rose-300 text-rose-950',
                'summary': (
                    '🔴 Nivel 1 (Colapso Sistémico): Se suprimen al 100 % los Bloques 2 y 3 (Velocidad y Potencia), '
                    'el Bloque 4 pasa a bombeo regenerativo (RIR 5–6 con carga mínima) y el Bloque 5 a Zona 2 sin impacto.'
                ),
            }
        if scheme == 'Esquema_Fatiga':
            return {
                'scheme': 'Esquema Fatiga (Fatiga Moderada)',
                'badge': '🟡 Nivel 2 · Esquema Fatiga',
                'color': 'amber',
                'badge_class': 'bg-amber-100 text-amber-900 border-amber-300',
                'banner_class': 'bg-amber-50 border-amber-300 text-amber-950',
                'summary': (
                    '🟡 Nivel 2 (Fatiga Moderada): Se amplía la movilidad en B1 (+1 serie), B2 y B3 pasan a fluidez '
                    'técnica submáxima, se recorta 1 serie y RPE en accesorios de B4 y B5 conmuta a Zona 2 regenerativa.'
                ),
            }
        return {
            'scheme': 'Esquema Normal',
            'badge': f'🟢 Nivel {self.readiness_level or 4} · Esquema Normal',
            'color': 'emerald',
            'badge_class': 'bg-emerald-100 text-emerald-900 border-emerald-300',
            'banner_class': 'bg-emerald-50/70 border-emerald-200 text-emerald-950',
            'summary': (
                f'🟢 Nivel {self.readiness_level or 4} (Disposición Verde): '
                'Esquema Normal activo con el 100 % de los bloques y cargas prescritos.'
            ),
        }

    def __str__(self):
        """Devuelve la identificación de la sesión vinculada a su plan de entrenamiento."""
        return f"Sesión: {self.workout_plan}"


class LoggedExercise(models.Model):
    """
    Agrupador de series ejecutadas en una sesión de entrenamiento para un ejercicio planificado,
    incluyendo el estado del Árbol Autónomo de Sustitución por Dolor Articular (`pain_status`).
    """

    PAIN_STATUS_CHOICES = [
        ('normal', 'Sin molestia (Ejercicio principal)'),
        ('option_a', 'Opción A (Regresión Isométrica: Isopush / Isohold)'),
        ('option_b', 'Opción B (Cambio de Vector Mecánico)'),
        ('omitted_injury', 'OMITIDO_POR_LESION'),
    ]

    workout_session = models.ForeignKey(WorkoutSession, on_delete=models.CASCADE, related_name='logged_exercises', verbose_name=_('sesión de entrenamiento'))
    planned_exercise = models.ForeignKey(PlannedExercise, on_delete=models.CASCADE, related_name='logs', verbose_name=_('ejercicio planificado'))
    pain_status = models.CharField(
        _('estado de dolor articular (⚠️)'),
        max_length=20,
        choices=PAIN_STATUS_CHOICES,
        default='normal',
    )
    substituted_exercise = models.ForeignKey(
        Exercise,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='substituted_in_logs',
        verbose_name=_('ejercicio activo por sustitución A/B'),
    )
    actual_sets = models.CharField(_('series reales'), max_length=50, blank=True)
    actual_reps = models.CharField(_('repeticiones reales'), max_length=50, blank=True)
    actual_load = models.CharField(_('carga real'), max_length=50, blank=True)
    actual_rpe = models.CharField(_('RPE real'), max_length=50, blank=True)
    notes = models.TextField(_('notas'), blank=True)

    # Temporización del ejercicio en el modo en vivo
    started_at = models.DateTimeField(_('hora de inicio'), null=True, blank=True)
    finished_at = models.DateTimeField(_('hora de finalización'), null=True, blank=True)

    class Meta:
        verbose_name = _('ejercicio registrado')
        verbose_name_plural = _('ejercicios registrados')

    @property
    def is_omitted_by_injury(self) -> bool:
        return self.pain_status == 'omitted_injury'

    @property
    def active_exercise(self) -> Exercise:
        """Devuelve el ejercicio efectivamente activo (sustituto Opción A/B o el prescrito original)."""
        if self.substituted_exercise_id and self.pain_status in ('option_a', 'option_b'):
            return self.substituted_exercise
        base_ex = self.planned_exercise.exercise
        if self.pain_status == 'option_a' and base_ex.regression_option_a_id:
            return base_ex.regression_option_a
        if self.pain_status == 'option_b' and base_ex.regression_option_b_id:
            return base_ex.regression_option_b
        return base_ex

    @property
    def active_video_url(self) -> str:
        """Devuelve la URL de vídeo correspondiente al estado actual del árbol de dolor articular."""
        base_ex = self.planned_exercise.exercise
        if self.pain_status == 'option_a':
            return base_ex.effective_option_a_video_url
        if self.pain_status == 'option_b':
            return base_ex.effective_option_b_video_url
        if self.pain_status == 'omitted_injury':
            return ''
        return base_ex.video_url or ''

    def apply_pain_tree_action(self, action: str = 'advance') -> str:
        """
        Avanza o conmuta el Árbol Autónomo de Sustitución por Dolor Articular (§4.2):
          - `normal` -> `option_a` (Regresión Isométrica) -> `option_b` (Cambio de Vector) -> `omitted_injury` (`OMITIDO_POR_LESION`).
          - Si falta Opción A o B en el ejercicio base, salta automáticamente al siguiente peldaño disponible.
          - Al llegar a `omitted_injury`, notifica automáticamente al entrenador (`TrainerNotification`).
        """
        base_ex = self.planned_exercise.exercise
        opt_a = base_ex.regression_option_a
        opt_b = base_ex.regression_option_b

        req = (action or 'advance').strip().lower()
        if req == 'reset' or req == 'normal':
            target = 'normal'
        elif req in ('option_a', 'option_b', 'omitted_injury'):
            target = req
        else:
            # Transición progresiva automática
            if self.pain_status == 'normal':
                if opt_a is not None:
                    target = 'option_a'
                elif opt_b is not None:
                    target = 'option_b'
                else:
                    target = 'omitted_injury'
            elif self.pain_status == 'option_a':
                if opt_b is not None:
                    target = 'option_b'
                else:
                    target = 'omitted_injury'
            elif self.pain_status == 'option_b':
                target = 'omitted_injury'
            else:
                target = 'normal'

        if target == 'option_a' and opt_a is None:
            target = 'option_b' if opt_b is not None else 'omitted_injury'
        if target == 'option_b' and opt_b is None:
            target = 'omitted_injury'

        self.pain_status = target
        if target == 'option_a':
            self.substituted_exercise = opt_a
        elif target == 'option_b':
            self.substituted_exercise = opt_b
        else:
            self.substituted_exercise = None

        if target == 'omitted_injury':
            now = timezone.now()
            if self.started_at is None:
                self.started_at = now
            if self.finished_at is None:
                self.finished_at = now
            self.notes = "OMITIDO_POR_LESION (persiste molestia articular en Opción A y Opción B)"
        self.save()

        if target == 'omitted_injury':
            plan = self.planned_exercise.workout_plan
            if plan.trainer_id:
                athlete_name = plan.athlete.user.display_name
                alert_msg = (
                    f"⚠️ OMITIDO_POR_LESION: {athlete_name} reportó dolor persistente en "
                    f"'{base_ex.name}' ({plan.name})."
                )
                TrainerNotification.objects.create(
                    trainer=plan.trainer,
                    athlete=plan.athlete,
                    event_type='injury_omitted',
                    message=alert_msg[:300],
                )

        return self.pain_status

    @property
    def is_in_progress(self):
        return self.started_at is not None and self.finished_at is None and not self.is_omitted_by_injury

    @property
    def is_started(self):
        return self.started_at is not None

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            delta = self.finished_at - self.started_at
            return int(delta.total_seconds())
        return 0

    @property
    def is_rm_exercise(self):
        return is_rm_based_exercise(self.planned_exercise)

    @property
    def best_1rm(self):
        """Mejor 1RM estimado entre las series registradas de este ejercicio en esta sesión."""
        best = 0.0
        for s in self.sets.all():
            est = s.est_1rm
            if est and est > best:
                best = est
        return round(best, 1) if best else 0.0

    def __str__(self):
        """Devuelve una representación del ejercicio registrado."""
        return f"Log: {self.planned_exercise.exercise.name}"


class LoggedSet(models.Model):
    """
    Registro individual de una serie ejecutada, guardando repeticiones reales,
    peso (kg), RPE individual y fecha/hora de finalización.
    """

    logged_exercise = models.ForeignKey(LoggedExercise, on_delete=models.CASCADE, related_name='sets', verbose_name=_('ejercicio registrado'))
    set_number = models.PositiveIntegerField(_('número de serie'), default=1)
    reps = models.PositiveIntegerField(_('repeticiones reales'), default=0)
    weight_kg = models.DecimalField(_('peso real (kg)'), max_digits=6, decimal_places=2, default=0.0)
    rpe = models.DecimalField(_('RPE'), max_digits=3, decimal_places=1, null=True, blank=True)
    completed_at = models.DateTimeField(_('hora completada'), auto_now_add=True)

    class Meta:
        verbose_name = _('serie registrada')
        verbose_name_plural = _('series registradas')
        ordering = ['set_number']

    @property
    def est_1rm(self):
        from .analytics import estimate_1rm
        return estimate_1rm(self.weight_kg, self.reps)

    @property
    def pct_1rm(self):
        from .analytics import pct_of_1rm
        return pct_of_1rm(self.weight_kg, self.est_1rm)

    def __str__(self):
        """Devuelve la descripción del número de serie, peso, repeticiones y RPE."""
        return f"Serie {self.set_number}: {self.weight_kg}kg x {self.reps} (RPE {self.rpe})"


class MMATriageProfile(models.Model):
    """
    Ficha Única de Ingesta, Biometría y Triage Clínico del Sistema AM para luchadores de MMA.
    Actúa como Single Source of Truth editable de forma continua por el atleta (Flujos A y B)
    y blinda en el servidor las directrices privadas y el cerrojo manual del entrenador.
    """

    # --- Sección 1: Identificación y Calendario Competitivo ---
    TACTICAL_STYLE_CHOICES = [
        ('mma_hibrido', 'MMA Híbrido'),
        ('dominancia_grappling', 'Dominancia Grappling'),
        ('dominancia_striking', 'Dominancia Striking'),
    ]

    WEIGH_IN_RULE_CHOICES = [
        ('profesional_24h', 'Profesional: 1 día antes (24-36h)'),
        ('amateur_mismo_dia', 'Amateur: Mismo día / Un par de horas antes'),
    ]

    BODY_COMP_GOAL_CHOICES = [
        ('mantenimiento', 'Mantenimiento'),
        ('corte_peso', 'Corte de peso'),
        ('ganancia_muscular', 'Ganancia muscular'),
    ]

    # --- Sección 2: Experiencia Técnica ---
    STRENGTH_EXPERIENCE_CHOICES = [
        ('novato', 'Novato'),
        ('intermedio', 'Intermedio'),
        ('avanzado', 'Avanzado'),
    ]

    OLYMPIC_LIFTS_CHOICES = [
        ('domina_motivado', 'Domina y motivado'),
        ('no_domina_motivado', 'No domina pero motivado para aprender'),
        ('sin_interes_molestias', 'Sin interés o molestias'),
    ]

    # --- Sección 3: Batería de Tests y Biometría ---
    RM_FORMAT_CHOICES = [
        ('3rm', '3RM (3 Repeticiones Máximas)'),
        ('1rm', '1RM (1 Repetición Máxima)'),
    ]

    WINGATE_MODALITY_CHOICES = [
        ('airbike_w', 'AirBike (Vatios medios - W)'),
        ('pista_m', 'Pista (Metros)'),
        ('assault_runner_m', 'Assault Runner (Metros)'),
    ]

    ISA_ANGLE_CHOICES = [
        ('estrecho', 'Estrecho (< 85º - Arquetipo Elástico)'),
        ('neutro', 'Neutro (85º a 95º - Arquetipo Híbrido)'),
        ('ancho', 'Ancho (> 95º - Arquetipo Muscular)'),
    ]

    # --- Sección 4: Logística, Inventario, Salud y Marco Legal ---
    AVAILABLE_DAYS_CHOICES = [
        (2, '2 días por semana'),
        (3, '3 días por semana'),
        (4, '4 días por semana'),
    ]

    TATAMI_VOLUME_CHOICES = [
        ('baja', 'Baja'),
        ('media', 'Media'),
        ('alta', 'Alta'),
    ]

    WEEKDAY_CHOICES = [
        ('lunes', 'Lunes'),
        ('martes', 'Martes'),
        ('miercoles', 'Miércoles'),
        ('jueves', 'Jueves'),
        ('viernes', 'Viernes'),
        ('sabado', 'Sábado'),
        ('domingo', 'Domingo'),
    ]

    OCCUPATIONAL_ACTIVITY_CHOICES = [
        ('sedentario', 'Sedentario (Oficina / Estudio)'),
        ('fisico_activo', 'Físico Activo (Trabajo de pie / Esfuerzo físico)'),
    ]

    JOINT_PAIN_CHOICES = [
        ('Hombros', 'Hombros'),
        ('Lumbares', 'Lumbares'),
        ('Rodillas', 'Rodillas'),
        ('Munecas', 'Muñecas'),
        ('Tobillos', 'Tobillos'),
        ('Cuello', 'Cuello'),
        ('Codos', 'Codos'),
        ('Cadera', 'Cadera'),
    ]

    # --- Bloque Exclusivo Backend (Privado Entrenador - Sección 2.2.2) ---
    HARD_OVERRIDE_CHOICES = [
        ('cortocircuito_novato', 'Forzar Cortocircuito de Novato (Edad Entrenamiento = 0)'),
        ('abrir_candado_olimpico', 'Abrir manualmente Candado Olímpico'),
        ('cerrar_candado_olimpico', 'Cerrar manualmente Candado Olímpico'),
        ('activar_candado_empuje', 'Activar Candado de Empuje'),
        ('activar_candado_excentrico', 'Activar Candado Excéntrico Absoluto'),
    ]

    BIOMECHANICAL_VETO_CHOICES = [
        ('veto_carga_axial_espinal', 'Veto Carga Axial Espinal'),
        ('veto_empuje_vertical_overhead', 'Veto Empuje Vertical Overhead'),
        ('veto_empuje_horizontal_barra', 'Veto Empuje Horizontal con Barra'),
        ('veto_traccion_pronacion', 'Veto Tracción en Pronación'),
        ('veto_impacto_pliometrico_inferior', 'Veto Impacto Pliométrico Inferior'),
        ('veto_sprints_lineales_suelo', 'Veto Sprints Lineales en Suelo'),
    ]

    REVIEW_STATUS_CHOICES = [
        ('borrador', 'Borrador / Incompleto'),
        ('pendiente_revision', 'Pendiente de Revisión'),
        ('aprobado', 'Aprobado (Cerrojo Activo)'),
    ]

    athlete = models.OneToOneField(
        AthleteProfile,
        on_delete=models.CASCADE,
        related_name='mma_triage',
        verbose_name=_('deportista'),
    )

    # Sección 1
    fasting_weight_kg = models.DecimalField(
        _('peso corporal actual en ayunas (kg)'),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    target_weight_category_kg = models.DecimalField(
        _('peso de la categoría objetivo (kg)'),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    tactical_style = models.CharField(
        _('estilo táctico predominante'),
        max_length=30,
        choices=TACTICAL_STYLE_CHOICES,
        default='mma_hibrido',
    )
    next_fight_date = models.DateField(
        _('fecha del próximo combate'),
        null=True,
        blank=True,
        help_text=_('Déjalo en blanco si te encuentras en Off-Season sin pelea cerrada.'),
    )
    weigh_in_rule = models.CharField(
        _('reglamentación de pesaje'),
        max_length=30,
        choices=WEIGH_IN_RULE_CHOICES,
        default='profesional_24h',
    )
    body_composition_goal = models.CharField(
        _('objetivo de composición corporal'),
        max_length=30,
        choices=BODY_COMP_GOAL_CHOICES,
        default='mantenimiento',
    )

    # Sección 2
    strength_experience = models.CharField(
        _('experiencia en entrenamiento de fuerza'),
        max_length=20,
        choices=STRENGTH_EXPERIENCE_CHOICES,
        default='novato',
    )
    olympic_lifts_relation = models.CharField(
        _('relación con levantamientos olímpicos'),
        max_length=30,
        choices=OLYMPIC_LIFTS_CHOICES,
        default='no_domina_motivado',
    )

    # Sección 3.1: Test de Fuerza (RM)
    knows_rm_marks = models.BooleanField(
        _('conoce sus marcas recientes de RM'),
        default=False,
    )
    rm_format = models.CharField(
        _('formato de marcas RM'),
        max_length=10,
        choices=RM_FORMAT_CHOICES,
        default='3rm',
    )
    back_squat_rm_kg = models.DecimalField(
        _('sentadilla trasera (kg)'),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    bench_press_rm_kg = models.DecimalField(
        _('press banca (kg)'),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    strict_pullup_external_load_kg = models.DecimalField(
        _('dominada estricta - solo lastre externo (kg)'),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Sección 3.2: Test Metabólico Doble Wingate
    wingate_modality = models.CharField(
        _('medio utilizado en Doble Wingate'),
        max_length=30,
        choices=WINGATE_MODALITY_CHOICES,
        blank=True,
        default='',
    )
    wingate_sprint_1 = models.DecimalField(
        _('marca Sprint 1 (30s)'),
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    wingate_sprint_2 = models.DecimalField(
        _('marca Sprint 2 (30s tras 1 min pasivo)'),
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Sección 3.3: Biometría Torácico-Pélvica (Ángulo ISA)
    isa_angle = models.CharField(
        _('biometría ángulo ISA'),
        max_length=20,
        choices=ISA_ANGLE_CHOICES,
        blank=True,
        default='',
    )

    # Sección 4: Logística, Inventario Estricto, Salud y Marco Legal
    available_days_per_week = models.PositiveSmallIntegerField(
        _('días disponibles para preparación física'),
        choices=AVAILABLE_DAYS_CHOICES,
        default=3,
    )
    can_separate_block_5 = models.BooleanField(
        _('disponibilidad para separar el Bloque 5 (Cardio) de las pesas'),
        default=False,
    )
    available_equipment = models.JSONField(
        _('inventario estricto de equipamiento'),
        default=list,
        blank=True,
    )
    tatami_weekly_volume = models.CharField(
        _('volumen semanal en tatami'),
        max_length=15,
        choices=TATAMI_VOLUME_CHOICES,
        default='media',
    )
    hard_sparring_days = models.JSONField(
        _('días habituales de sparring duro'),
        default=list,
        blank=True,
    )
    occupational_activity = models.CharField(
        _('actividad laboral'),
        max_length=20,
        choices=OCCUPATIONAL_ACTIVITY_CHOICES,
        default='sedentario',
    )
    has_nutritional_support = models.BooleanField(
        _('cuenta con apoyo nutricional profesional'),
        default=False,
    )
    par_q_has_risk = models.BooleanField(
        _('alerta filtro médico PAR-Q (algún síntoma cardiovascular/sistémico)'),
        default=False,
    )
    current_joint_pain_zones = models.JSONField(
        _('zonas de dolor o molestia articular actual'),
        default=list,
        blank=True,
    )

    # Casillas legales obligatorias
    accepted_terms_of_service = models.BooleanField(_('acepta términos de servicio'), default=False)
    accepted_privacy_policy = models.BooleanField(_('acepta política de privacidad'), default=False)
    accepted_medical_waiver = models.BooleanField(
        _('acepta descargo de responsabilidad médico y asunción de riesgo'),
        default=False,
    )
    legal_accepted_at = models.DateTimeField(_('fecha de aceptación legal'), null=True, blank=True)

    # --- BLOQUE EXCLUSIVO DEL BACKEND (100% INVISIBLE PARA EL ATLETA) ---
    hard_overrides_locks = models.JSONField(
        _('hard overrides de candados (entrenador)'),
        default=list,
        blank=True,
    )
    biomechanical_vetoes = models.JSONField(
        _('vetos biomecánicos (entrenador)'),
        default=list,
        blank=True,
    )
    private_clinical_notes = models.TextField(
        _('directrices clínicas privadas (Prompt Override)'),
        blank=True,
    )
    approved_for_generation = models.BooleanField(
        _('aprobar y habilitar generación (Cerrojo Manual)'),
        default=False,
    )
    review_status = models.CharField(
        _('estado de auditoría'),
        max_length=25,
        choices=REVIEW_STATUS_CHOICES,
        default='borrador',
        db_index=True,
    )
    last_athlete_submission_at = models.DateTimeField(
        _('último envío del atleta'),
        null=True,
        blank=True,
    )
    last_trainer_review_at = models.DateTimeField(
        _('última revisión del entrenador'),
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        TrainerProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_mma_triages',
        verbose_name=_('revisado por'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('ficha de triage MMA (Sistema AM)')
        verbose_name_plural = _('fichas de triage MMA (Sistema AM)')

    def clean(self):
        super().clean()
        locks = set(self.hard_overrides_locks or [])
        if 'abrir_candado_olimpico' in locks and 'cerrar_candado_olimpico' in locks:
            raise ValidationError({
                'hard_overrides_locks': _(
                    'No se puede forzar simultáneamente Abrir y Cerrar el Candado Olímpico.'
                )
            })

    @property
    def is_legally_complete(self) -> bool:
        return bool(
            self.accepted_terms_of_service
            and self.accepted_privacy_policy
            and self.accepted_medical_waiver
        )

    @property
    def has_light_medball(self) -> bool:
        """Regla RFD de Balón Medicinal: verifica disponibilidad de balones ligeros <= 6 kg."""
        return 'Balones medicinales LIGEROS (<= 6 kg)' in (self.available_equipment or [])

    @property
    def weeks_until_fight(self):
        """Semanas restantes entre hoy y la fecha del combate (None si está en Off-Season)."""
        if not self.next_fight_date:
            return None
        delta_days = (self.next_fight_date - timezone.now().date()).days
        return max(0, delta_days // 7)

    @property
    def computed_phase_label(self) -> str:
        """Fase competitiva oficial según semanas restantes (Módulo 1 del Sistema AM)."""
        weeks = self.weeks_until_fight
        if weeks is None or weeks > 12:
            return 'Off-Season (> 12 sem o sin fecha)'
        if 8 <= weeks <= 12:
            return f'Pre-Training Camp ({weeks} sem)'
        if 1 <= weeks <= 7:
            sub = 'Fase Base' if weeks > 4 else 'Tapering'
            return f'Training Camp - {sub} ({weeks} sem)'
        return 'Fight Week (< 1 sem)'

    @property
    def weight_cut_kg(self):
        """Magnitud absoluta del corte de peso en kg."""
        if self.fasting_weight_kg and self.target_weight_category_kg:
            diff = float(self.fasting_weight_kg) - float(self.target_weight_category_kg)
            return round(max(0.0, diff), 2)
        return None

    @property
    def weight_cut_pct(self):
        """Porcentaje de peso a recortar respecto al peso actual en ayunas."""
        if self.fasting_weight_kg and float(self.fasting_weight_kg) > 0 and self.target_weight_category_kg:
            diff = float(self.fasting_weight_kg) - float(self.target_weight_category_kg)
            if diff <= 0:
                return 0.0
            return round((diff / float(self.fasting_weight_kg)) * 100.0, 1)
        return None

    @property
    def squat_e1rm_kg(self):
        """1RM estimado en Sentadilla Trasera (e1RM = 3RM * 1.1 según Módulo 3)."""
        if not self.knows_rm_marks or not self.back_squat_rm_kg:
            return None
        factor = 1.1 if self.rm_format == '3rm' else 1.0
        return round(float(self.back_squat_rm_kg) * factor, 1)

    @property
    def squat_bw_ratio(self):
        """Ratio Fuerza Base en Sentadilla respecto al peso corporal (umbral Candado Olímpico >= 1.5x)."""
        e1rm = self.squat_e1rm_kg
        if e1rm and self.fasting_weight_kg and float(self.fasting_weight_kg) > 0:
            return round(e1rm / float(self.fasting_weight_kg), 2)
        return None

    @property
    def bench_e1rm_kg(self):
        """1RM estimado en Press Banca."""
        if not self.knows_rm_marks or not self.bench_press_rm_kg:
            return None
        factor = 1.1 if self.rm_format == '3rm' else 1.0
        return round(float(self.bench_press_rm_kg) * factor, 1)

    @property
    def pullup_e1rm_kg(self):
        """1RM estimado de Carga Total en Dominada Estricta (Peso_Actual + Lastre)."""
        if (
            not self.knows_rm_marks
            or not self.fasting_weight_kg
            or self.strict_pullup_external_load_kg is None
        ):
            return None
        total_load = float(self.fasting_weight_kg) + float(self.strict_pullup_external_load_kg)
        factor = 1.1 if self.rm_format == '3rm' else 1.0
        return round(total_load * factor, 1)

    @property
    def push_pull_ratio(self):
        """Ratio e1RM_Banca / e1RM_Dominada (umbral Candado de Empuje > 1.15)."""
        bench = self.bench_e1rm_kg
        pullup = self.pullup_e1rm_kg
        if bench and pullup and pullup > 0:
            return round(bench / pullup, 2)
        return None

    @property
    def wingate_drop_pct(self):
        """Porcentaje de caída entre Sprint 1 y Sprint 2 en el Test Doble Wingate."""
        if (
            self.wingate_sprint_1 is not None
            and float(self.wingate_sprint_1) > 0
            and self.wingate_sprint_2 is not None
        ):
            s1 = float(self.wingate_sprint_1)
            s2 = float(self.wingate_sprint_2)
            return round(((s1 - s2) / s1) * 100.0, 1)
        return None

    def submit_by_athlete(self) -> None:
        """
        Ejecuta el Protocolo de Seguridad 'Reset on Submit' (Flujo B del Sistema AM):
        - Sobrescribe únicamente los datos aportados por el atleta manteniendo intactos los
          filtros privados del entrenador y el ángulo ISA si ya estaba medido.
        - Pasa el estado automáticamente a 'pendiente_revision'.
        - Desmarca automáticamente el cerrojo `approved_for_generation` (FALSE).
        - Sincroniza el peso en ayunas con el perfil general del atleta y notifica al entrenador.
        """
        now = timezone.now()
        self.review_status = 'pendiente_revision'
        self.approved_for_generation = False
        self.last_athlete_submission_at = now
        if self.is_legally_complete and not self.legal_accepted_at:
            self.legal_accepted_at = now
        self.save()

        # Sincronizar peso y deporte MMA en AthleteProfile y AthleteProgressLog
        athlete = self.athlete
        profile_updated_fields = []
        if self.fasting_weight_kg is not None and athlete.weight != self.fasting_weight_kg:
            athlete.weight = self.fasting_weight_kg
            profile_updated_fields.append('weight')
        if athlete.sport != 'mma':
            athlete.sport = 'mma'
            profile_updated_fields.append('sport')
        if profile_updated_fields:
            profile_updated_fields.append('updated_at')
            athlete.save(update_fields=profile_updated_fields)

        if self.fasting_weight_kg is not None:
            AthleteProgressLog.objects.update_or_create(
                athlete=athlete,
                date=now.date(),
                defaults={
                    'weight': self.fasting_weight_kg,
                    'fat_percentage': athlete.fat_percentage,
                    'lean_mass_percentage': athlete.lean_mass_percentage,
                },
            )

        # Notificar al entrenador asignado (en app + correo)
        trainer_user = athlete.assigned_trainer
        if trainer_user and hasattr(trainer_user, 'trainer_profile'):
            athlete_name = (
                f"{athlete.user.first_name} {athlete.user.last_name}".strip()
                or athlete.user.email
            )
            alert_text = f"El atleta {athlete_name} ha actualizado su ficha."
            TrainerNotification.objects.create(
                trainer=trainer_user.trainer_profile,
                athlete=athlete,
                event_type='triage_updated',
                message=alert_text,
            )
            send_mail(
                subject=f"[Sistema AM] {alert_text}",
                message=(
                    f"Hola {trainer_user.display_name},\n\n"
                    f"{alert_text}\n"
                    "Por protocolo de seguridad (Reset on Submit), el estado de su ficha ha pasado a "
                    "PENDIENTE_REVISION y el cerrojo manual de generación se ha desactivado "
                    "hasta que audites los cambios en su expediente clínico.\n"
                ),
                from_email=None,
                recipient_list=[trainer_user.email],
                fail_silently=True,
            )

    def review_by_trainer(self, trainer_profile: TrainerProfile) -> None:
        """
        Registra la revisión clínica del entrenador y actualiza el estado según el Cerrojo Manual.
        """
        now = timezone.now()
        self.last_trainer_review_at = now
        self.reviewed_by = trainer_profile
        if self.is_legally_complete and not self.legal_accepted_at:
            self.legal_accepted_at = now

        if self.approved_for_generation:
            self.review_status = 'aprobado'
        else:
            self.review_status = 'pendiente_revision'
        self.save()

        if self.fasting_weight_kg is not None and self.athlete.weight != self.fasting_weight_kg:
            self.athlete.weight = self.fasting_weight_kg
            self.athlete.save(update_fields=['weight', 'updated_at'])

        # Marcar como leídas las alertas pendientes de cambio de ficha para este atleta
        TrainerNotification.objects.filter(
            trainer=trainer_profile,
            athlete=self.athlete,
            event_type='triage_updated',
            is_read=False,
        ).update(is_read=True)

    def __str__(self):
        return f"Triage MMA: {self.athlete.user.email} [{self.get_review_status_display()}]"


class TrainerNotification(models.Model):
    """
    Registro de alertas operativas y de seguridad clínica dirigidas al entrenador
    (cambios en ficha de triage, ejercicios omitidos por lesión, fatiga severa o fin de bloque).
    """

    EVENT_TYPE_CHOICES = [
        ('triage_updated', 'Ficha de Triage Actualizada'),
        ('injury_omitted', 'Ejercicio Omitido por Lesión'),
        ('low_readiness', 'Alerta de Disposición / Fatiga'),
        ('block_ending', 'Fin de Bloque Próximo'),
    ]

    trainer = models.ForeignKey(
        TrainerProfile,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name=_('entrenador'),
    )
    athlete = models.ForeignKey(
        AthleteProfile,
        on_delete=models.CASCADE,
        related_name='trainer_notifications',
        verbose_name=_('deportista'),
    )
    event_type = models.CharField(
        _('tipo de evento'),
        max_length=30,
        choices=EVENT_TYPE_CHOICES,
        default='triage_updated',
    )
    message = models.CharField(_('mensaje'), max_length=300)
    is_read = models.BooleanField(_('leída'), default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('notificación de entrenador')
        verbose_name_plural = _('notificaciones de entrenador')
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_event_type_display()}] {self.message}"

