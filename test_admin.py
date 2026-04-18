import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django.template.context
def _basecontext_copy_patch(self):
    duplicate = self.__class__.__new__(self.__class__)
    duplicate.__dict__.update(self.__dict__)
    duplicate.dicts = self.dicts[:]
    return duplicate
django.template.context.BaseContext.__copy__ = _basecontext_copy_patch
django.setup()
from django.test import RequestFactory
from django.contrib.admin.sites import site
from users.models import CustomUser

rf = RequestFactory()
req = rf.get('/admin/users/customuser/add/')
u = CustomUser.objects.filter(is_superuser=True).first()
req.user = u
model_admin = site._registry[CustomUser]
response = model_admin.add_view(req)
if hasattr(response, 'render'):
    response.render()
    print("Add View Rendered OK, HTTP", response.status_code)
