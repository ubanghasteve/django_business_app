from rest_framework import status, generics, viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from django.contrib.auth import login, logout
from django.contrib.auth.signals import user_logged_in, user_logged_out

from .models import User
from .serializers import (
    UserSerializer, UserRegistrationSerializer, UserLoginSerializer,
    UserProfileSerializer, ChangePasswordSerializer, UserDetailSerializer
)


class _HasDjangoPerm(permissions.BasePermission):
    """DRF permission that requires a Django permission (e.g. 'accounts.view_user')."""
    def __init__(self, perm):
        self.perm = perm

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.has_perm(self.perm)


class RegisterAPIView(generics.CreateAPIView):
    """API view for user registration"""
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # Create or get token for the user
        token, created = Token.objects.get_or_create(user=user)
        
        return Response({
            'message': 'User registered successfully',
            'user': UserSerializer(user).data,
            'token': token.key
        }, status=status.HTTP_201_CREATED)


class LoginAPIView(APIView):
    """API view for user login"""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            
            # Create or get token for the user
            token, created = Token.objects.get_or_create(user=user)
            
            # Send login signal
            user_logged_in.send(sender=user.__class__, request=request, user=user)
            
            return Response({
                'message': 'Login successful',
                'user': UserDetailSerializer(user).data,
                'token': token.key
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LogoutAPIView(APIView):
    """API view for user logout"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            # Delete the user's token
            request.user.auth_token.delete()
            
            # Send logout signal
            user_logged_out.send(sender=request.user.__class__, request=request, user=request.user)
            
            return Response({
                'message': 'Logout successful'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'error': 'Something went wrong during logout'
            }, status=status.HTTP_400_BAD_REQUEST)


class ProfileAPIView(generics.RetrieveUpdateAPIView):
    """API view for user profile"""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response({
            'message': 'Profile updated successfully',
            'user': serializer.data
        })


class ChangePasswordAPIView(APIView):
    """API view for changing password"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = request.user
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            
            # Update token after password change
            Token.objects.filter(user=user).delete()
            token = Token.objects.create(user=user)
            
            return Response({
                'message': 'Password changed successfully',
                'token': token.key
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for user management (admin only)"""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        """Override permissions based on action. List/create require view_user/add_user; others require auth or change_user."""
        if self.action in ('list',):
            return [permissions.IsAuthenticated(), _HasDjangoPerm('accounts.view_user')()]
        if self.action in ('create',):
            return [permissions.IsAuthenticated(), _HasDjangoPerm('accounts.add_user')()]
        if self.action in ('retrieve', 'update', 'partial_update', 'me'):
            return [permissions.IsAuthenticated()]
        if self.action == 'set_password':
            return [permissions.IsAuthenticated(), _HasDjangoPerm('accounts.change_user')()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """Scope to current user's account; list only if user has accounts.view_user."""
        user = self.request.user
        if not user.is_authenticated:
            return User.objects.none()
        account = getattr(user, 'account', None)
        if account is None:
            return User.objects.filter(id=user.id)
        if user.has_perm('accounts.view_user'):
            return User.objects.filter(account=account)
        return User.objects.filter(id=user.id)

    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'retrieve':
            return UserDetailSerializer
        return UserSerializer

    @action(detail=True, methods=['post'])
    def set_password(self, request, pk=None):
        """Set password for a user. Requires accounts.change_user."""
        if not request.user.has_perm('accounts.change_user'):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        user = self.get_object()
        password = request.data.get('password')
        
        if not password:
            return Response({'error': 'Password is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        user.set_password(password)
        user.save()
        
        return Response({'message': 'Password set successfully'})

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get current user's profile"""
        serializer = UserDetailSerializer(request.user)
        return Response(serializer.data)
