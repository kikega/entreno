from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, UserChangeForm
from django.utils.translation import gettext_lazy as _
from .models import CustomUser, AthleteProfile, AthleteProgressLog

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

class AthleteProfileForm(forms.ModelForm):
    first_name = forms.CharField(
        label=_("Nombre"),
        required=True,
        widget=forms.TextInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary'})
    )
    last_name = forms.CharField(
        label=_("Apellidos"),
        required=True,
        widget=forms.TextInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary'})
    )

    class Meta:
        model = AthleteProfile
        fields = ['weight', 'height', 'fat_percentage', 'lean_mass_percentage']
        widgets = {
            'weight': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'step': '0.01'}),
            'height': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'step': '0.01'}),
            'fat_percentage': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'step': '0.01'}),
            'lean_mass_percentage': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name

    def save(self, commit=True):
        athlete = super().save(commit=False)
        if commit:
            athlete.save()
            # Also save user fields
            user = athlete.user
            user.first_name = self.cleaned_data['first_name']
            user.last_name = self.cleaned_data['last_name']
            user.save()
        return athlete

class AthleteProgressLogForm(forms.ModelForm):
    class Meta:
        model = AthleteProgressLog
        fields = ['weight', 'fat_percentage', 'lean_mass_percentage', 'date']
        widgets = {
            'weight': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'step': '0.01', 'required': 'required'}),
            'fat_percentage': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'step': '0.01'}),
            'lean_mass_percentage': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'step': '0.01'}),
            'date': forms.DateInput(attrs={'class': 'peer block w-full appearance-none rounded-md border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary', 'type': 'date'}),
        }
