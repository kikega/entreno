from django import forms
from django.db.models import Q
from django.utils.html import format_html
from users.models import AthleteProfile
from .models import (
    WorkoutPlan, PlannedExercise, WorkoutSession, Exercise,
    MMATriageProfile, Macrocycle, MacrocycleBlock,
)

GENERIC_INPUT_CLASS = (
    'mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 '
    'text-base text-slate-900 shadow-sm focus:border-primary focus:ring-primary '
    'focus:outline-none transition'
)


class WorkoutPlanForm(forms.ModelForm):
    """
    Formulario para la creación y edición de planes de entrenamiento asignados a un deportista.
    """
    class Meta:

        model = WorkoutPlan
        fields = ['name', 'athlete', 'target_date']
        widgets = {
            'target_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario personalizando los widgets y filtrando el queryset de deportistas
        para incluir tanto a los asignados al entrenador como a sí mismo si dispone de perfil dual.
        """
        trainer = kwargs.pop('trainer', None)

        super().__init__(*args, **kwargs)
        
        # Filtrar deportistas: los asignados al entrenador o a sí mismo si es deportista
        if trainer:
            self.fields['athlete'].queryset = self.fields['athlete'].queryset.filter(
                Q(assigned_trainer=trainer.user) | Q(user=trainer.user)
            )
            
        for field in self.fields.values():
            field.widget.attrs.update({'class': GENERIC_INPUT_CLASS})


class CategoryAwareExerciseSelect(forms.Select):
    """
    Widget Select que inyecta `data-category` y `data-session-block` en cada `<option>`
    del catálogo de ejercicios para permitir el filtrado dinámico por categoría en la confección del plan.
    """

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, 'instance', None)
        if instance is not None:
            option['attrs']['data-category'] = getattr(instance, 'category', '') or ''
            option['attrs']['data-session-block'] = getattr(instance, 'session_block', '') or ''
        return option


class PlannedExerciseForm(forms.ModelForm):
    """
    Formulario para prescribir un ejercicio individual dentro de un plan de entrenamiento.
    Permite acceder a todos los ejercicios del catálogo del sistema independientemente del creador,
    con soporte de filtrado por categoría de ejercicio.
    """
    class Meta:

        model = PlannedExercise
        fields = [
            'exercise', 'session_block', 'order', 'sets', 'reps',
            'load', 'rpe', 'rir', 'tempo', 'focus', 'rest', 'notes',
        ]
        widgets = {
            'exercise': CategoryAwareExerciseSelect(),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario aplicando estilos CSS y cargando los ejercicios ordenados (filtrables por categoría)."""
        category = kwargs.pop('category', None)
        super().__init__(*args, **kwargs)
        qs = Exercise.objects.all().order_by('name')
        if category and category in dict(Exercise.CATEGORY_CHOICES):
            qs = qs.filter(category=category)
        self.fields['exercise'].queryset = qs
        self.fields['order'].required = False
        self.fields['session_block'].required = False
        self.fields['session_block'].choices = [
            ('', 'Automático (según bloque del ejercicio en catálogo)'),
            *Exercise.SESSION_BLOCK_CHOICES,
        ]

        for field in self.fields.values():
            field.widget.attrs.update({'class': GENERIC_INPUT_CLASS})

    def clean_order(self):
        val = self.cleaned_data.get('order')
        return val if val is not None else 0


class ExerciseForm(forms.ModelForm):
    """
    Formulario para crear y editar ejercicios del catálogo del entrenador.
    """

    sport_tags = forms.MultipleChoiceField(
        label='Etiquetas de deportes',
        choices=AthleteProfile.SPORT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = Exercise
        fields = ['name', 'category', 'movement_pattern', 'sport_tags', 'description', 'video_url']
        widgets = {
            'description': forms.Textarea(attrs={
                'rows': 8,
                'placeholder': '### 1. Nombre y objetivo\n### 2. Anatomía muscular\n### 3. Ejecución técnica paso a paso\n### 4. Errores más comunes y cómo evitarlos\n### 5. Claves de seguridad y variantes'
            }),
            'video_url': forms.URLInput(attrs={'placeholder': 'https://ejemplo.com/video'}),
        }


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': GENERIC_INPUT_CLASS})

        self.fields['sport_tags'].widget.attrs.pop('class', None)
        self.fields['sport_tags'].widget.attrs['class'] = 'space-y-2'
        self.fields['sport_tags'].label = 'Etiquetas de deportes'
        self.fields['sport_tags'].help_text = 'Selecciona los deportes a los que está orientado el ejercicio.'


class WorkoutSessionForm(forms.ModelForm):
    """
    Formulario para registrar los datos globales al completar una sesión de entrenamiento (duración, calorías, FC, RPE y notas).
    """
    class Meta:

        model = WorkoutSession
        fields = ['duration_minutes', 'calories_burned', 'avg_heart_rate', 'session_rpe', 'notes']
        widgets = {
            'duration_minutes': forms.NumberInput(attrs={
                'class': 'mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 shadow-sm focus:border-accent focus:ring-accent focus:outline-none transition',
                'placeholder': 'Ej: 60',
                'min': '1'
            }),
            'calories_burned': forms.NumberInput(attrs={
                'class': 'mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 shadow-sm focus:border-accent focus:ring-accent focus:outline-none transition',
                'placeholder': 'Ej: 450',
                'min': '0'
            }),
            'avg_heart_rate': forms.NumberInput(attrs={
                'class': 'mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 shadow-sm focus:border-accent focus:ring-accent focus:outline-none transition',
                'placeholder': 'Ej: 135',
                'min': '40'
            }),
            'session_rpe': forms.NumberInput(attrs={
                'class': 'mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 shadow-sm focus:border-accent focus:ring-accent focus:outline-none transition',
                'placeholder': 'Ej: 8.0 (Escala 1 a 10)',
                'min': '1',
                'max': '10',
                'step': '0.5'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 shadow-sm focus:border-accent focus:ring-accent focus:outline-none transition',
                'rows': 3,
                'placeholder': 'Escribe cómo te has sentido, tus sensaciones, marcas especiales, etc.'
            }),
        }


class AthleteMMATriageForm(forms.ModelForm):
    """
    Formulario Único de Ingesta y Actualización Continua para atletas de MMA (Secciones 1 a 4).
    Garantiza el blindaje estricto de columnas: jamás expone ni sobrescribe los candados manuales,
    vetos biomecánicos, notas clínicas privadas ni el cerrojo de aprobación del entrenador.
    """

    EQUIPMENT_CHOICES = [(item, item) for item in Exercise.AM_CANONICAL_EQUIPMENT]

    available_equipment = forms.MultipleChoiceField(
        label='Inventario estricto de equipamiento disponible',
        choices=EQUIPMENT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    hard_sparring_days = forms.MultipleChoiceField(
        label='Días habituales de sparring duro',
        choices=MMATriageProfile.WEEKDAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    current_joint_pain_zones = forms.MultipleChoiceField(
        label='Zonas de dolor o molestia articular actual',
        choices=MMATriageProfile.JOINT_PAIN_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = MMATriageProfile
        fields = [
            # Sección 1: Identificación y Calendario Competitivo
            'fasting_weight_kg',
            'target_weight_category_kg',
            'tactical_style',
            'next_fight_date',
            'weigh_in_rule',
            'body_composition_goal',
            # Sección 2: Experiencia Técnica
            'strength_experience',
            'olympic_lifts_relation',
            # Sección 3: Batería de Tests y Biometría (Opcional / Actualizable)
            'knows_rm_marks',
            'rm_format',
            'back_squat_rm_kg',
            'bench_press_rm_kg',
            'strict_pullup_external_load_kg',
            'wingate_modality',
            'wingate_sprint_1',
            'wingate_sprint_2',
            'isa_angle',
            # Sección 4: Logística, Inventario, Salud y Marco Legal
            'available_days_per_week',
            'can_separate_block_5',
            'available_equipment',
            'tatami_weekly_volume',
            'hard_sparring_days',
            'occupational_activity',
            'has_nutritional_support',
            'par_q_has_risk',
            'current_joint_pain_zones',
            'accepted_terms_of_service',
            'accepted_privacy_policy',
            'accepted_medical_waiver',
        ]
        widgets = {
            'fasting_weight_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS,
                'min': '35', 'max': '200', 'step': '0.1',
                'inputmode': 'decimal', 'placeholder': 'Ej: 77.5',
            }),
            'target_weight_category_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS,
                'min': '35', 'max': '200', 'step': '0.1',
                'inputmode': 'decimal', 'placeholder': 'Ej: 70.3',
            }),
            'next_fight_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'type': 'date', 'class': GENERIC_INPUT_CLASS,
            }),
            'back_squat_rm_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS,
                'min': '10', 'max': '450', 'step': '0.5',
                'inputmode': 'decimal', 'placeholder': 'Ej: 130',
            }),
            'bench_press_rm_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS,
                'min': '10', 'max': '350', 'step': '0.5',
                'inputmode': 'decimal', 'placeholder': 'Ej: 95',
            }),
            'strict_pullup_external_load_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS,
                'min': '0', 'max': '200', 'step': '0.5',
                'inputmode': 'decimal', 'placeholder': 'Ej: 20 (0 si es sin lastre)',
            }),
            'wingate_modality': forms.Select(attrs={'class': GENERIC_INPUT_CLASS}),
            'wingate_sprint_1': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS,
                'min': '1', 'max': '3000', 'step': '0.1',
                'inputmode': 'decimal', 'placeholder': 'Ej: 620',
            }),
            'wingate_sprint_2': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS,
                'min': '1', 'max': '3000', 'step': '0.1',
                'inputmode': 'decimal', 'placeholder': 'Ej: 510',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fasting_weight_kg'].required = True
        self.fields['target_weight_category_kg'].required = True
        self.fields['accepted_terms_of_service'].required = True
        self.fields['accepted_privacy_policy'].required = True
        self.fields['accepted_medical_waiver'].required = True
        if self.instance and self.instance.pk:
            self.initial['available_equipment'] = list(self.instance.available_equipment or [])
            self.initial['hard_sparring_days'] = list(self.instance.hard_sparring_days or [])
            self.initial['current_joint_pain_zones'] = list(self.instance.current_joint_pain_zones or [])

    def clean(self):
        cleaned_data = super().clean()
        s1 = cleaned_data.get('wingate_sprint_1')
        s2 = cleaned_data.get('wingate_sprint_2')
        modality = cleaned_data.get('wingate_modality')

        if (s1 is not None or s2 is not None) and not modality:
            self.add_error('wingate_modality', 'Selecciona el medio utilizado para registrar las marcas del Doble Wingate.')
        if (s1 is not None and s2 is None) or (s2 is not None and s1 is None):
            self.add_error('wingate_sprint_2', 'Si registras el Test Doble Wingate, indica tanto el Sprint 1 como el Sprint 2.')

        if not cleaned_data.get('accepted_terms_of_service'):
            self.add_error('accepted_terms_of_service', 'Debes aceptar los términos de servicio.')
        if not cleaned_data.get('accepted_privacy_policy'):
            self.add_error('accepted_privacy_policy', 'Debes aceptar la política de privacidad.')
        if not cleaned_data.get('accepted_medical_waiver'):
            self.add_error('accepted_medical_waiver', 'Debes aceptar el descargo de responsabilidad médico y asunción de riesgo.')

        return cleaned_data


class TrainerMMATriageClinicalForm(forms.ModelForm):
    """
    Formulario Exclusivo de Entrevista Clínica y Cerrojo Manual para el Entrenador (Sección 2.2.2).
    Permite completar la batería biométrica (Ángulo ISA, marcas RM/Wingate, acuerdos legales) y
    configurar las columnas privadas de Backend: Hard Overrides, Vetos Biomecánicos,
    Prompt Override Privado y el Cerrojo Manual `approved_for_generation`.
    """

    hard_overrides_locks = forms.MultipleChoiceField(
        label='Hard Overrides de Candados (Uso Exclusivo Entrenador)',
        choices=MMATriageProfile.HARD_OVERRIDE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    biomechanical_vetoes = forms.MultipleChoiceField(
        label='Vetos Biomecánicos Estrictos (Uso Exclusivo Entrenador)',
        choices=MMATriageProfile.BIOMECHANICAL_VETO_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    current_joint_pain_zones = forms.MultipleChoiceField(
        label='Zonas de dolor articular reportadas / confirmadas',
        choices=MMATriageProfile.JOINT_PAIN_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = MMATriageProfile
        fields = [
            # Biometría y Tests completables en videollamada
            'fasting_weight_kg',
            'target_weight_category_kg',
            'next_fight_date',
            'isa_angle',
            'knows_rm_marks',
            'rm_format',
            'back_squat_rm_kg',
            'bench_press_rm_kg',
            'strict_pullup_external_load_kg',
            'wingate_modality',
            'wingate_sprint_1',
            'wingate_sprint_2',
            'current_joint_pain_zones',
            # Confirmación de marco legal en entrevista
            'accepted_terms_of_service',
            'accepted_privacy_policy',
            'accepted_medical_waiver',
            # Columnas privadas exclusivas del Backend
            'hard_overrides_locks',
            'biomechanical_vetoes',
            'private_clinical_notes',
            'approved_for_generation',
        ]
        widgets = {
            'fasting_weight_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS, 'min': '35', 'max': '200', 'step': '0.1', 'inputmode': 'decimal',
            }),
            'target_weight_category_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS, 'min': '35', 'max': '200', 'step': '0.1', 'inputmode': 'decimal',
            }),
            'next_fight_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'type': 'date', 'class': GENERIC_INPUT_CLASS,
            }),
            'back_squat_rm_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS, 'min': '10', 'max': '450', 'step': '0.5', 'inputmode': 'decimal',
            }),
            'bench_press_rm_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS, 'min': '10', 'max': '350', 'step': '0.5', 'inputmode': 'decimal',
            }),
            'strict_pullup_external_load_kg': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS, 'min': '0', 'max': '200', 'step': '0.5', 'inputmode': 'decimal',
            }),
            'wingate_modality': forms.Select(attrs={'class': GENERIC_INPUT_CLASS}),
            'wingate_sprint_1': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS, 'min': '1', 'max': '3000', 'step': '0.1', 'inputmode': 'decimal',
            }),
            'wingate_sprint_2': forms.NumberInput(attrs={
                'class': GENERIC_INPUT_CLASS, 'min': '1', 'max': '3000', 'step': '0.1', 'inputmode': 'decimal',
            }),
            'private_clinical_notes': forms.Textarea(attrs={
                'class': GENERIC_INPUT_CLASS,
                'rows': 5,
                'placeholder': (
                    'Notas confidenciales de la entrevista clínica y directrices de jerarquía suprema '
                    '(Prompt_Override). El atleta jamás puede ver este bloque.'
                ),
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['hard_overrides_locks'] = list(self.instance.hard_overrides_locks or [])
            self.initial['biomechanical_vetoes'] = list(self.instance.biomechanical_vetoes or [])
            self.initial['current_joint_pain_zones'] = list(self.instance.current_joint_pain_zones or [])

    def clean(self):
        cleaned_data = super().clean()
        locks = set(cleaned_data.get('hard_overrides_locks') or [])
        if 'abrir_candado_olimpico' in locks and 'cerrar_candado_olimpico' in locks:
            self.add_error(
                'hard_overrides_locks',
                'No puedes seleccionar simultáneamente Abrir y Cerrar el Candado Olímpico.',
            )

        if cleaned_data.get('approved_for_generation'):
            legal_ok = (
                cleaned_data.get('accepted_terms_of_service')
                and cleaned_data.get('accepted_privacy_policy')
                and cleaned_data.get('accepted_medical_waiver')
            )
            if not legal_ok:
                self.add_error(
                    'approved_for_generation',
                    'Para activar el Cerrojo Manual (APROBAR_Y_GENERAR_IA) deben estar confirmadas las 3 cláusulas legales.',
                )
        return cleaned_data


class MacrocycleBlockConfigForm(forms.ModelForm):
    """
    Formulario de auditoría del entrenador para ajustar parámetros estructurales de un bloque
    (subfase Base/Tapering, número de semanas, días por semana, fechas y notas privadas).
    """

    class Meta:
        model = MacrocycleBlock
        fields = [
            'title', 'subphase', 'weeks_count', 'sessions_per_week',
            'start_date', 'end_date', 'trainer_notes',
        ]
        widgets = {
            'weeks_count': forms.NumberInput(attrs={'min': '1', 'max': '6'}),
            'sessions_per_week': forms.NumberInput(attrs={'min': '1', 'max': '6'}),
            'start_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'end_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'trainer_notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Notas privadas del entrenador sobre este bloque (invisibles para el deportista).',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': GENERIC_INPUT_CLASS})


class BlockProgressionPrescribeForm(forms.Form):
    """
    Formulario rápido para prescribir un ejercicio y su progresión a lo largo de las
    semanas de un `MacrocycleBlock` en un `day_number` concreto, respetando la protección
    no destructiva de sesiones ya completadas o con series registradas.
    """

    exercise = forms.ModelChoiceField(
        label='Ejercicio del catálogo',
        queryset=Exercise.objects.none(),
        widget=CategoryAwareExerciseSelect(),
    )
    session_block = forms.ChoiceField(
        label='Bloque concurrente de sesión (B1-B5)',
        required=False,
        choices=[('', 'Automático según catálogo'), *Exercise.SESSION_BLOCK_CHOICES],
    )
    day_number = forms.IntegerField(label='Día de sesión', min_value=1, max_value=6, initial=1)
    order = forms.IntegerField(label='Orden en la sesión', min_value=0, max_value=50, initial=1)
    tempo = forms.CharField(label='Tempo', max_length=50, required=False, widget=forms.TextInput(attrs={'placeholder': 'Ej: 3-1-X-0'}))
    rest = forms.CharField(label='Descanso', max_length=50, required=False, widget=forms.TextInput(attrs={'placeholder': 'Ej: 120s'}))
    focus = forms.CharField(label='Foco técnico', max_length=100, required=False, widget=forms.TextInput(attrs={'placeholder': 'Ej: Intención concéntrica máxima'}))
    notes = forms.CharField(label='Indicaciones', required=False, widget=forms.Textarea(attrs={'rows': 2}))

    # Progresión de Semana 1 a Semana 4 (base del mesociclo)
    w1_sets = forms.CharField(label='Sem 1 · Series', max_length=20, initial='3')
    w1_reps = forms.CharField(label='Sem 1 · Reps', max_length=20, initial='5')
    w1_rir = forms.CharField(label='Sem 1 · RIR', max_length=20, required=False, initial='3')
    w1_rpe = forms.CharField(label='Sem 1 · RPE', max_length=20, required=False, initial='7')
    w1_load = forms.CharField(label='Sem 1 · Carga', max_length=30, required=False)

    w2_sets = forms.CharField(label='Sem 2 · Series', max_length=20, required=False, initial='3')
    w2_reps = forms.CharField(label='Sem 2 · Reps', max_length=20, required=False, initial='4')
    w2_rir = forms.CharField(label='Sem 2 · RIR', max_length=20, required=False, initial='2')
    w2_rpe = forms.CharField(label='Sem 2 · RPE', max_length=20, required=False, initial='8')
    w2_load = forms.CharField(label='Sem 2 · Carga', max_length=30, required=False)

    w3_sets = forms.CharField(label='Sem 3 · Series', max_length=20, required=False, initial='4')
    w3_reps = forms.CharField(label='Sem 3 · Reps', max_length=20, required=False, initial='3')
    w3_rir = forms.CharField(label='Sem 3 · RIR', max_length=20, required=False, initial='2')
    w3_rpe = forms.CharField(label='Sem 3 · RPE', max_length=20, required=False, initial='8')
    w3_load = forms.CharField(label='Sem 3 · Carga', max_length=30, required=False)

    w4_sets = forms.CharField(label='Sem 4 · Series', max_length=20, required=False, initial='2')
    w4_reps = forms.CharField(label='Sem 4 · Reps', max_length=20, required=False, initial='3')
    w4_rir = forms.CharField(label='Sem 4 · RIR', max_length=20, required=False, initial='3')
    w4_rpe = forms.CharField(label='Sem 4 · RPE', max_length=20, required=False, initial='7')
    w4_load = forms.CharField(label='Sem 4 · Carga', max_length=30, required=False)

    def __init__(self, *args, **kwargs):
        category = kwargs.pop('category', None)
        super().__init__(*args, **kwargs)
        qs = Exercise.objects.all().order_by('session_block', 'name')
        if category and category in dict(Exercise.CATEGORY_CHOICES):
            qs = qs.filter(category=category)
        self.fields['exercise'].queryset = qs
        for field in self.fields.values():
            field.widget.attrs.update({'class': GENERIC_INPUT_CLASS})

    def week_spec(self, week_num: int) -> dict[str, str]:
        """Devuelve la pauta para `week_num` (1..6), usando Semana 4 como fallback para semanas 5-6."""
        idx = min(max(1, week_num), 4)
        sets = (self.cleaned_data.get(f'w{idx}_sets') or self.cleaned_data.get('w1_sets') or '3').strip()
        reps = (self.cleaned_data.get(f'w{idx}_reps') or self.cleaned_data.get('w1_reps') or '5').strip()
        rir = (self.cleaned_data.get(f'w{idx}_rir') if self.cleaned_data.get(f'w{idx}_rir') != '' else self.cleaned_data.get('w1_rir', '')).strip()
        rpe = (self.cleaned_data.get(f'w{idx}_rpe') if self.cleaned_data.get(f'w{idx}_rpe') != '' else self.cleaned_data.get('w1_rpe', '')).strip()
        load = (self.cleaned_data.get(f'w{idx}_load') or self.cleaned_data.get('w1_load') or '').strip()
        return {
            'sets': sets,
            'reps': reps,
            'rir': rir,
            'rpe': rpe,
            'load': load,
        }
