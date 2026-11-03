from django.contrib import admin
from .models import (
    Exercise, WorkoutPlan, PlannedExercise, WorkoutSession, LoggedExercise,
    DisciplineTemplate, TemplateExercise, ExerciseDisciplineFit,
    MMATriageProfile, TrainerNotification, Macrocycle, MacrocycleBlock,
)
from .ml_engine import SportTemplateEngine


class MacrocycleBlockInline(admin.TabularInline):
    model = MacrocycleBlock
    extra = 0
    fields = [
        'block_number', 'phase_type', 'subphase', 'title',
        'weeks_count', 'sessions_per_week', 'is_published', 'published_at',
    ]
    readonly_fields = ['published_at']


class MacrocycleAdmin(admin.ModelAdmin):
    list_display = ['name', 'athlete', 'trainer', 'target_fight_date', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'athlete__user__email', 'trainer__user__email']
    inlines = [MacrocycleBlockInline]


class MacrocycleBlockAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'macrocycle', 'block_number', 'phase_type',
        'subphase', 'weeks_count', 'is_published', 'published_at',
    ]
    list_filter = ['phase_type', 'subphase', 'is_published']
    search_fields = ['title', 'macrocycle__athlete__user__email']


class PlannedExerciseInline(admin.TabularInline):
    """Configuración en línea para gestionar ejercicios planificados dentro del administrador de WorkoutPlan."""
    model = PlannedExercise
    extra = 1


class WorkoutPlanAdmin(admin.ModelAdmin):
    """Configuración del panel de administración para el modelo WorkoutPlan."""
    list_display = ['name', 'athlete', 'trainer', 'macrocycle_block', 'week_number', 'day_number', 'target_date', 'is_completed']
    list_filter = ['is_completed', 'target_date', 'macrocycle_block__phase_type']
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
    list_display = [
        'code', 'name', 'session_block', 'category',
        'patron_vector', 'complexity_level', 'lock_route',
        'compromised_joint', 'created_by',
    ]
    list_display_links = ['code', 'name']
    list_filter = [
        'session_block', 'category', 'movement_pattern',
        'patron_vector', 'lock_route', 'complexity_level',
        'isa_tag', 'contractile_regime', 'compromised_joint',
    ]
    search_fields = ['code', 'name', 'description']
    autocomplete_fields = ['regression_option_a', 'regression_option_b']
    fieldsets = (
        ('Identificación y Clasificación General', {
            'fields': (
                ('code', 'name'),
                ('category', 'movement_pattern'),
                'sport_tags',
                'video_url',
                'description',
                'created_by',
            )
        }),
        ('Taxonomía Biomecánica Sistema AM (MMA)', {
            'classes': ('collapse',),
            'fields': (
                ('session_block', 'patron_vector'),
                ('lock_route', 'complexity_level'),
                ('isa_tag', 'contractile_regime', 'compromised_joint'),
                'required_equipment',
            )
        }),
        ('Árbol Autónomo de Sustitución por Dolor Articular (A / B)', {
            'classes': ('collapse',),
            'fields': (
                ('regression_option_a', 'option_a_video_url'),
                ('regression_option_b', 'option_b_video_url'),
            )
        }),
    )
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


class MMATriageProfileAdmin(admin.ModelAdmin):
    list_display = [
        'athlete', 'review_status', 'approved_for_generation',
        'tactical_style', 'next_fight_date', 'isa_angle',
        'last_athlete_submission_at', 'last_trainer_review_at',
    ]
    list_filter = [
        'review_status', 'approved_for_generation', 'tactical_style',
        'strength_experience', 'isa_angle', 'par_q_has_risk',
    ]
    search_fields = ['athlete__user__email', 'athlete__user__first_name', 'athlete__user__last_name']
    readonly_fields = ['legal_accepted_at', 'last_athlete_submission_at', 'last_trainer_review_at']


class TrainerNotificationAdmin(admin.ModelAdmin):
    list_display = ['trainer', 'athlete', 'event_type', 'message', 'is_read', 'created_at']
    list_filter = ['event_type', 'is_read', 'created_at']
    search_fields = ['message', 'athlete__user__email', 'trainer__user__email']


admin.site.register(Exercise, ExerciseAdmin)
admin.site.register(DisciplineTemplate, DisciplineTemplateAdmin)
admin.site.register(Macrocycle, MacrocycleAdmin)
admin.site.register(MacrocycleBlock, MacrocycleBlockAdmin)
admin.site.register(WorkoutPlan, WorkoutPlanAdmin)
admin.site.register(WorkoutSession, WorkoutSessionAdmin)
admin.site.register(MMATriageProfile, MMATriageProfileAdmin)
admin.site.register(TrainerNotification, TrainerNotificationAdmin)
