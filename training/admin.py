from django.contrib import admin
from .models import (
    Exercise, WorkoutPlan, PlannedExercise, WorkoutSession, LoggedExercise,
    DisciplineTemplate, TemplateExercise, ExerciseDisciplineFit,
)
from .ml_engine import SportTemplateEngine


class PlannedExerciseInline(admin.TabularInline):
    """Configuración en línea para gestionar ejercicios planificados dentro del administrador de WorkoutPlan."""
    model = PlannedExercise
    extra = 1


class WorkoutPlanAdmin(admin.ModelAdmin):
    """Configuración del panel de administración para el modelo WorkoutPlan."""
    list_display = ['name', 'athlete', 'trainer', 'target_date', 'is_completed']
    list_filter = ['is_completed', 'target_date']
    inlines = [PlannedExerciseInline]


class LoggedExerciseInline(admin.TabularInline):
    """Configuración en línea para ver ejercicios registrados dentro del administrador de WorkoutSession."""
    model = LoggedExercise
    extra = 0


class WorkoutSessionAdmin(admin.ModelAdmin):
    """Configuración del panel de administración para el modelo WorkoutSession."""
    list_display = ['workout_plan', 'athlete', 'date_completed', 'duration_minutes']
    inlines = [LoggedExerciseInline]


class ExerciseDisciplineFitInline(admin.TabularInline):
    model = ExerciseDisciplineFit
    extra = 1


class ExerciseAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'movement_pattern', 'created_by']
    list_filter = ['category', 'movement_pattern']
    search_fields = ['name']
    inlines = [ExerciseDisciplineFitInline]


class TemplateExerciseInline(admin.TabularInline):
    model = TemplateExercise
    extra = 1


@admin.action(description='Sugerir ejercicios del catálogo para la disciplina')
def suggest_more(modeladmin, request, queryset):
    """Añade a cada plantilla seleccionada los ejercicios del catálogo con mayor
    ajuste (fit) para su deporte que aún no estén incluidos."""
    for template in queryset:
        suggestions = SportTemplateEngine.suggest_more_exercises(
            template.sport, template=template
        )
        last_order = (template.items.order_by('-order').values_list('order', flat=True).first() or 0)
        for i, exercise in enumerate(suggestions, start=1):
            TemplateExercise.objects.get_or_create(
                template=template,
                exercise=exercise,
                defaults={'order': last_order + i},
            )
        if suggestions:
            modeladmin.message_user(
                request,
                f'Se añadieron {len(suggestions)} ejercicios sugeridos a "{template.name}".',
            )
        else:
            modeladmin.message_user(
                request, f'"{template.name}" ya incluye todos los ejercicios con buen ajuste.', 'warning'
            )


class DisciplineTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'sport', 'is_default', 'is_active', 'created_by']
    list_filter = ['sport', 'is_default', 'is_active']
    search_fields = ['name', 'focus']
    inlines = [TemplateExerciseInline]
    actions = [suggest_more]


admin.site.register(Exercise, ExerciseAdmin)
admin.site.register(DisciplineTemplate, DisciplineTemplateAdmin)
admin.site.register(WorkoutPlan, WorkoutPlanAdmin)
admin.site.register(WorkoutSession, WorkoutSessionAdmin)
