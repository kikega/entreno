from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, TrainerProfile, AthleteProfile

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['email', 'is_staff', 'is_active']
    search_fields = ['email']
    ordering = ['email']

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(TrainerProfile)
admin.site.register(AthleteProfile)
