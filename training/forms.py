from django import forms
from .models import WorkoutPlan, PlannedExercise

class WorkoutPlanForm(forms.ModelForm):
    class Meta:
        model = WorkoutPlan
        fields = ['name', 'athlete', 'target_date']
        widgets = {
            'target_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        trainer = kwargs.pop('trainer', None)
        super().__init__(*args, **kwargs)
        
        # Filtrar deportistas para que solo aparezcan los asignados a este entrenador
        if trainer:
            self.fields['athlete'].queryset = self.fields['athlete'].queryset.filter(assigned_trainer=trainer.user)
            
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary sm:text-sm'})


class PlannedExerciseForm(forms.ModelForm):
    class Meta:
        model = PlannedExercise
        fields = ['exercise', 'order', 'sets', 'reps', 'load', 'rpe', 'rir', 'tempo', 'focus', 'rest', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            # Apply Tailwind classes globally to all inputs
            field.widget.attrs.update({'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary sm:text-sm'})
