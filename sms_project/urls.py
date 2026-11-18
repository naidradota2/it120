"""Root URL configuration for sms_project."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),  # login / logout
    path('', include('sms_app.urls')),
]
