from django.contrib import admin

from .models import Contact, Message


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number', 'created_at')
    search_fields = ('name', 'phone_number')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'status', 'provider', 'created_at', 'status_checked_at')
    list_filter = ('status', 'provider')
    search_fields = ('recipient', 'body')
    readonly_fields = ('created_at', 'status_checked_at')
