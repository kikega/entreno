import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from users.forms import CustomUserCreationForm
form = CustomUserCreationForm(data={'email': 'admin@test.com', 'password1': 'Admin12345!', 'password2': 'Admin12345!'})
if not form.is_valid():
    print(form.errors)
else:
    user = form.save()
    print("Saved user:", user)
