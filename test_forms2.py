import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from users.forms import CustomUserCreationForm
form = CustomUserCreationForm(data={'email': 'test2@test.com', 'password1': 'admin123', 'password2': 'admin123'})
if not form.is_valid():
    print(form.errors)
else:
    user = form.save()
    print("Saved user:", user)
