from django.urls import path
from . import views

app_name = 'requisitions'

urlpatterns = [
    path('', views.requisition_list, name='list'),
    path('modal/', views.requisition_list_modal, name='list_modal'),
    path('create/', views.requisition_create, name='create'),
    path('<int:pk>/', views.requisition_detail, name='detail'),
    path('<int:pk>/edit/', views.requisition_edit, name='edit'),
    path('<int:pk>/delete/', views.requisition_delete, name='delete'),
    path('<int:pk>/print/', views.requisition_print, name='print'),
    path('<int:pk>/pdf/', views.requisition_pdf, name='pdf'),
    path('<int:pk>/update-status/', views.requisition_update_status, name='update_status'),
]
