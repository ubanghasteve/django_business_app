from django.urls import path
from . import views

app_name = 'staff_offences'

urlpatterns = [
    path('', views.register_list, name='list'),
    path('create/', views.register_create, name='create'),
    path('create/ajax/', views.register_create_ajax, name='create_ajax'),
    path('<int:pk>/', views.register_detail, name='detail'),
    path('<int:pk>/delete/', views.register_delete, name='delete'),
    path('<int:pk>/print/', views.register_print, name='print'),
    path('<int:pk>/pdf/', views.register_pdf, name='pdf'),
    path('<int:pk>/signature/', views.signature_upload_ajax, name='signature_upload'),
    path('<int:pk>/signature/clear/', views.signature_clear_ajax, name='signature_clear'),
    path('<int:pk>/payment-status/', views.payment_status_update_ajax, name='payment_status'),
    path('<int:pk>/entries/add/', views.entry_create, name='entry_create'),
    path('<int:pk>/entries/add/ajax/', views.entry_create_ajax, name='entry_create_ajax'),
    path('<int:pk>/entries/<int:entry_pk>/edit/', views.entry_edit, name='entry_edit'),
    path('<int:pk>/entries/<int:entry_pk>/edit/ajax/', views.entry_edit_ajax, name='entry_edit_ajax'),
    path('<int:pk>/entries/<int:entry_pk>/delete/', views.entry_delete, name='entry_delete'),
    path('<int:pk>/entries/<int:entry_pk>/delete/ajax/', views.entry_delete_ajax, name='entry_delete_ajax'),
]
