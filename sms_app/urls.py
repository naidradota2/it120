from django.urls import path

from . import views

app_name = 'sms_app'

urlpatterns = [
    path('', views.compose, name='compose'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('history/', views.history, name='history'),
    path('history/refresh/', views.refresh_all, name='refresh_all'),
    path('messages/<int:pk>/', views.message_detail, name='message_detail'),
    path('messages/<int:pk>/refresh/', views.message_refresh, name='message_refresh'),
    path('contacts/', views.contact_list, name='contact_list'),
    path('contacts/new/', views.contact_create, name='contact_create'),
    path('contacts/<int:pk>/edit/', views.contact_edit, name='contact_edit'),
    path('contacts/<int:pk>/delete/', views.contact_delete, name='contact_delete'),
]
