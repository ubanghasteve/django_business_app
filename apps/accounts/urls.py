from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'accounts'

urlpatterns = [
    # Authentication URLs
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.RegisterView.as_view(), name='register'),
    
    # Password reset URLs
    path('password_reset/', 
         views.CustomPasswordResetView.as_view(), 
         name='password_reset'),
    path('password_reset/done/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='accounts/password_reset_done.html'
         ),
         name='password_reset_done'),
    path('reset/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             template_name='accounts/password_reset_confirm.html',
             success_url='/auth/reset/complete/'
         ),
         name='password_reset_confirm'),
    path('reset/complete/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='accounts/password_reset_complete.html'
         ),
         name='password_reset_complete'),
    
    # Required password change (first login after HR-created portal account)
    path('password-change-required/', views.password_change_required, name='password_change_required'),
    # Profile URLs
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.ProfileEditView.as_view(), name='profile_edit'),
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Security URLs
    path('security/', views.security_dashboard, name='security_dashboard'),
    path('security/team/', views.subuser_list, name='subuser_list'),
    path('security/team/add/', views.subuser_create, name='subuser_create'),
    path('security/team/<int:subuser_id>/edit/', views.subuser_edit, name='subuser_edit'),
    path('security/team/<int:subuser_id>/delete/', views.subuser_delete, name='subuser_delete'),
    path('security/sessions/', views.session_history, name='session_history'),
    path('security/activities/', views.activity_log, name='activity_log'),
    path('security/activity/<uuid:activity_id>/', views.activity_detail, name='activity_detail'),
    path('security/session/<uuid:session_id>/', views.session_detail, name='session_detail'),
    path('security/session/<uuid:session_id>/terminate/', views.terminate_session_view, name='terminate_session'),
    path('security/sessions/terminate-all/', views.terminate_all_sessions, name='terminate_all_sessions'),
    
    # Admin Security URLs (staff only)
    path('security/admin/', views.admin_security_overview, name='admin_security_overview'),
    path('security/admin/user/<int:user_id>/', views.admin_user_activities, name='admin_user_activities'),
    path('security/admin/live-users/', views.live_users, name='live_users'),

    # Account roles (tenant-scoped groups & permissions)
    path('security/roles/', views.account_role_list, name='role_list'),
    path('security/roles/add/', views.account_role_create, name='role_create'),
    path('security/roles/<int:role_id>/edit/', views.account_role_edit, name='role_edit'),
    path('security/roles/<int:role_id>/delete/', views.account_role_delete, name='role_delete'),
    path('security/roles/<int:role_id>/members/', views.account_role_members, name='role_members'),

    # Legacy profile URL for backward compatibility
    path('profile-old/', views.ProfileView.as_view(), name='profile_old'),
    
    # Alternative function-based views (uncomment if preferred)
    # path('login/', views.login_view, name='login'),
    # path('logout/', views.logout_view, name='logout'),
    # path('register/', views.register_view, name='register'),
]
