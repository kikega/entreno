from django import forms
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, UserChangeForm
from django.utils.translation import gettext_lazy as _
from .models import CustomUser

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('email', 'first_name', 'last_name')

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ('email', 'first_name', 'last_name')

class CustomAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label=_("Correo electrónico"),
        widget=forms.EmailInput(attrs={'autofocus': True, 'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 pb-2 pt-5 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'placeholder': ' '})
    )
    password = forms.CharField(
        label=_("Contraseña"),
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 pb-2 pt-5 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'placeholder': ' '})
    )
