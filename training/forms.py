from django import forms
from django.utils.html import format_html
from users.models import AthleteProfile
from .models import WorkoutPlan, PlannedExercise, WorkoutSession, Exercise

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
        para incluir únicamente a los asignados al entrenador actual.
        """
        trainer = kwargs.pop('trainer', None)

        super().__init__(*args, **kwargs)
        
        # Filtrar deportistas para que solo aparezcan los asignados a este entrenador
        if trainer:
            self.fields['athlete'].queryset = self.fields['athlete'].queryset.filter(assigned_trainer=trainer.user)
            
        for field in self.fields.values():
            field.widget.attrs.update({'class': GENERIC_INPUT_CLASS})


class PlannedExerciseForm(forms.ModelForm):
    """
    Formulario para prescribir un ejercicio individual dentro de un plan de entrenamiento.
    """
    class Meta:

        model = PlannedExercise
        fields = ['exercise', 'order', 'sets', 'reps', 'load', 'rpe', 'rir', 'tempo', 'focus', 'rest', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario aplicando estilos CSS unificados a los widgets."""
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.widget.attrs.update({'class': GENERIC_INPUT_CLASS})


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
            'description': forms.Textarea(attrs={'rows': 3}),
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
        fields = ['duration_minutes', 'calories_burned', 'avg_heart_rate', 'notes']
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
            'notes': forms.Textarea(attrs={
                'class': 'mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 shadow-sm focus:border-accent focus:ring-accent focus:outline-none transition',
                'rows': 3,
                'placeholder': 'Escribe cómo te has sentido, tus sensaciones, marcas especiales, etc.'
            }),
        }