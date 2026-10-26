from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, UserChangeForm, PasswordChangeForm
from django.utils.translation import gettext_lazy as _
from .models import CustomUser, AthleteProfile, AthleteProgressLog

class CustomUserCreationForm(UserCreationForm):
    """Formulario para la creación de nuevos usuarios utilizando email como credencial principal."""
    class Meta:
        model = CustomUser
        fields = ('email', 'first_name', 'last_name', 'profile_picture')

class CustomUserChangeForm(UserChangeForm):
    """Formulario para la edición de datos de usuario en la administración."""
    class Meta:
        model = CustomUser
        fields = ('email', 'first_name', 'last_name', 'profile_picture')

class CustomAuthenticationForm(AuthenticationForm):
    """Formulario de autenticación personalizado que sustituye el nombre de usuario por email."""
    username = forms.EmailField(

        label=_("Correo electrónico"),
        widget=forms.EmailInput(attrs={'autofocus': True, 'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 pb-2 pt-5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm', 'placeholder': ' '})
    )
    password = forms.CharField(
        label=_("Contraseña"),
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 pb-2 pt-5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm', 'placeholder': ' '})
    )

    def clean_username(self):
        """Normaliza el correo a minúsculas y elimina espacios iniciales/finales."""
        username = self.cleaned_data.get('username')
        if username:
            return username.strip().lower()
        return username

class AthleteProfileForm(forms.ModelForm):
    """
    Formulario para actualizar la información antropométrica, deportiva y personal (nombre/apellidos/correo/foto) de un atleta.
    """
    first_name = forms.CharField(
        label=_("Nombre"),
        required=True,
        widget=forms.TextInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm'})
    )
    last_name = forms.CharField(
        label=_("Apellidos"),
        required=True,
        widget=forms.TextInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm'})
    )
    email = forms.EmailField(
        label=_("Correo electrónico"),
        required=False,
        widget=forms.EmailInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm'})
    )
    profile_picture = forms.ImageField(
        label=_("Fotografía de perfil"),
        required=False,
        widget=forms.FileInput(attrs={
            'id': 'profile_picture_input',
            'class': 'hidden',
            'accept': 'image/*',
        })
    )
    delete_profile_picture = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput()
    )

    class Meta:
        model = AthleteProfile
        fields = ['weight', 'height', 'fat_percentage', 'lean_mass_percentage', 'sport', 'experience_level', 'training_goal']
        widgets = {
            'weight': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm', 'step': '0.01'}),
            'height': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm', 'step': '0.01'}),
            'fat_percentage': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm', 'step': '0.01'}),
            'lean_mass_percentage': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm', 'step': '0.01'}),
            'sport': forms.Select(attrs={'class': 'peer block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm'}),
            'experience_level': forms.Select(attrs={'class': 'peer block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm'}),
            'training_goal': forms.Select(attrs={'class': 'peer block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm'}),
        }

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario cargando el nombre, apellidos y correo actuales desde el modelo CustomUser del deportista."""
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email

    def clean_email(self):
        """Valida y normaliza el correo electrónico del deportista, conservando el actual si no se envía."""
        email = self.cleaned_data.get('email')
        user = getattr(self.instance, 'user', None)
        if not email:
            return user.email if user else ''
        email = email.strip().lower()
        qs = CustomUser.objects.filter(email__iexact=email)
        if user and user.pk:
            qs = qs.exclude(pk=user.pk)
        if qs.exists():
            raise forms.ValidationError(_("Ya existe otro usuario registrado con este correo electrónico."))
        return email

    def save(self, commit=True):
        """Guarda el perfil de deportista y actualiza simultáneamente los datos personales en la entidad CustomUser del deportista."""
        athlete = super().save(commit=False)

        if commit:
            athlete.save()
            # Actualizar exclusivamente el usuario asociado al perfil del deportista
            user = athlete.user
            user.first_name = self.cleaned_data['first_name']
            user.last_name = self.cleaned_data['last_name']
            if self.cleaned_data.get('email'):
                user.email = self.cleaned_data['email']
            if self.cleaned_data.get('delete_profile_picture'):
                if user.profile_picture:
                    user.profile_picture.delete(save=False)
                user.profile_picture = None
            elif self.cleaned_data.get('profile_picture'):
                user.profile_picture = self.cleaned_data['profile_picture']
            user.save()
        return athlete


class TrainerUserForm(forms.ModelForm):
    """
    Formulario para actualizar datos personales básicos (nombre, apellidos y foto)
    para usuarios con rol de entrenador que no disponen de perfil de deportista.
    """
    first_name = forms.CharField(
        label=_("Nombre"),
        required=True,
        widget=forms.TextInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm'})
    )
    last_name = forms.CharField(
        label=_("Apellidos"),
        required=True,
        widget=forms.TextInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-primary focus:ring-primary focus:outline-none transition shadow-sm'})
    )
    profile_picture = forms.ImageField(
        label=_("Fotografía de perfil"),
        required=False,
        widget=forms.FileInput(attrs={
            'id': 'profile_picture_input',
            'class': 'hidden',
            'accept': 'image/*',
        })
    )
    delete_profile_picture = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput()
    )

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name']

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('delete_profile_picture'):
            if user.profile_picture:
                user.profile_picture.delete(save=False)
            user.profile_picture = None
        elif self.cleaned_data.get('profile_picture'):
            user.profile_picture = self.cleaned_data['profile_picture']
        if commit:
            user.save()
        return user


class AthleteProgressLogForm(forms.ModelForm):
    """
    Formulario para el registro de mediciones de peso y composición corporal en una fecha determinada.
    """
    class Meta:

        model = AthleteProgressLog
        fields = ['weight', 'fat_percentage', 'lean_mass_percentage', 'date']
        widgets = {
            'weight': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-accent focus:ring-accent focus:outline-none transition shadow-sm', 'step': '0.01', 'required': 'required', 'placeholder': 'Ej: 74.5'}),
            'fat_percentage': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-accent focus:ring-accent focus:outline-none transition shadow-sm', 'step': '0.01', 'placeholder': 'Ej: 14.2'}),
            'lean_mass_percentage': forms.NumberInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-accent focus:ring-accent focus:outline-none transition shadow-sm', 'step': '0.01', 'placeholder': 'Ej: 81.3'}),
            'date': forms.DateInput(attrs={'class': 'peer block w-full appearance-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-accent focus:ring-accent focus:outline-none transition shadow-sm', 'type': 'date'}),
        }


class CustomPasswordChangeForm(PasswordChangeForm):
    """
    Formulario personalizado para el cambio de contraseña de usuarios autenticados.
    Aplica widgets y estilos consistentes con Tailwind CSS y etiquetas en español.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = _("Contraseña actual")
        self.fields['old_password'].widget.attrs.update({
            'class': 'peer block w-full appearance-none rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none transition shadow-sm pr-10',
            'placeholder': 'Introduce tu contraseña actual',
            'autocomplete': 'current-password',
        })
        self.fields['new_password1'].label = _("Nueva contraseña")
        self.fields['new_password1'].widget.attrs.update({
            'class': 'peer block w-full appearance-none rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none transition shadow-sm pr-10',
            'placeholder': 'Mínimo 8 caracteres',
            'autocomplete': 'new-password',
        })
        self.fields['new_password2'].label = _("Confirmar nueva contraseña")
        self.fields['new_password2'].widget.attrs.update({
            'class': 'peer block w-full appearance-none rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none transition shadow-sm pr-10',
            'placeholder': 'Repite la nueva contraseña',
            'autocomplete': 'new-password',
        })

