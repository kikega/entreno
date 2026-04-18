from django.contrib import admin
from .models import Exercise, WorkoutPlan, PlannedExercise, WorkoutSession, LoggedExercise

class PlannedExerciseInline(admin.TabularInline):
    model = PlannedExercise
    extra = 1

class WorkoutPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'athlete', 'trainer', 'target_date', 'is_completed']
    list_filter = ['is_completed', 'target_date']
    inlines = [PlannedExerciseInline]

class LoggedExerciseInline(admin.TabularInline):
    model = LoggedExercise
    extra = 0

class WorkoutSessionAdmin(admin.ModelAdmin):
    list_display = ['workout_plan', 'athlete', 'date_completed', 'duration_minutes']
    inlines = [LoggedExerciseInline]

admin.site.register(Exercise)
admin.site.register(WorkoutPlan, WorkoutPlanAdmin)
admin.site.register(WorkoutSession, WorkoutSessionAdmin)
