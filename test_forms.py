import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from users.forms import CustomUserCreationForm
form = CustomUserCreationForm()
print(form.fields.keys())
