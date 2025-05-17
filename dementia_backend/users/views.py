from django.shortcuts import render
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate, get_user_model
from rest_framework.permissions import IsAuthenticated, AllowAny
from .serializers import UserRegistrationSerializer, PatientSerializer
from .models import Patient
from .permissions import IsDoctor, IsPatient
import uuid
import random
import string

User = get_user_model()

class RegisterView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                "message": "User registered successfully",
                "user_type": user.user_type,
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh)
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class DoctorLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        slmc_id = request.data.get('slmc_id')
        password = request.data.get('password')

        if not slmc_id or not password:
            return Response({"error": "SLMC ID and password required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(slmc_id=slmc_id)
        except User.DoesNotExist:
            return Response({"error": "Invalid SLMC ID"}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(password):
            return Response({"error": "Invalid password"}, status=status.HTTP_400_BAD_REQUEST)

        if user.user_type != User.DOCTOR:
            return Response({"error": "Not a doctor account"}, status=status.HTTP_400_BAD_REQUEST)

        refresh = RefreshToken.for_user(user)
        return Response({
            "message": "Doctor login successful",
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh)
        }, status=status.HTTP_200_OK)
    
class PatientLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            return Response({"error": "Username and password required."}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(username=username, password=password)

        if not user or user.user_type != User.PATIENT:
            return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)

        refresh = RefreshToken.for_user(user)
        return Response({
            "message": "Patient login successful",
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
        }, status=status.HTTP_200_OK)

class LogoutView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        refresh_token = request.data.get('refresh_token')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"message": "Logout successful"}, status=status.HTTP_200_OK)
        return Response({"error": "Refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)

class PatientViewSet(viewsets.ModelViewSet):
    queryset = Patient.objects.all()
    serializer_class = PatientSerializer
    permission_classes = [IsAuthenticated, IsDoctor]

    def get_serializer_context(self):
        return {'request': self.request}

    def get_queryset(self):
        # Handle username filtering if provided
        username = self.request.query_params.get('username', None)
        if username:
            return Patient.objects.filter(
                doctor=self.request.user,
                user__username=username
            )
        return Patient.objects.filter(doctor=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        
        # For single patient search by username
        username = request.query_params.get('username', None)
        if username:
            if not queryset.exists():
                return Response([], status=status.HTTP_200_OK)
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)
        
        # Default list behavior
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        data = request.data

        # Generate a unique username
        username = f"pat_{uuid.uuid4().hex[:6]}"
        
        # Generate a random password
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))

        # Create the user
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=password,
            user_type=User.PATIENT,
            slmc_id=f"PAT-{uuid.uuid4().hex[:8].upper()}",
            first_name=data.get('first_name', 'Patient'),
            last_name=data.get('last_name', '')
        )

        # Create the patient linked to this user and the logged-in doctor
        patient = Patient.objects.create(
            user=user,
            doctor=request.user,
            age=data.get('age'),
            gender=data.get('gender'),
            address=data.get('address'),
            emergency_contact=data.get('emergency_contact'),
            medical_history=data.get('medical_history')
        )

        serializer = self.get_serializer(patient)
        return Response({
            "message": "Patient created successfully",
            "username": username,
            "password": password,
            "patient": serializer.data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.doctor != request.user:
            return Response(
                {"error": "You can only update your own patients"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Handle patient profile updates
        instance.age = request.data.get('age', instance.age)
        instance.gender = request.data.get('gender', instance.gender)
        instance.address = request.data.get('address', instance.address)
        instance.emergency_contact = request.data.get('emergency_contact', instance.emergency_contact)
        instance.medical_history = request.data.get('medical_history', instance.medical_history)
        instance.save()

        # Handle user updates if provided
        user = instance.user
        if 'first_name' in request.data:
            user.first_name = request.data['first_name']
        if 'last_name' in request.data:
            user.last_name = request.data['last_name']
        user.save()

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.doctor != request.user:
            return Response(
                {"error": "You can only delete your own patients"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Delete the associated user as well
        user = instance.user
        self.perform_destroy(instance)
        user.delete()

        return Response(
            {"message": "Patient and associated user deleted successfully"},
            status=status.HTTP_204_NO_CONTENT
        )

class PatientProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        try:
            patient = Patient.objects.get(user__username=username)
            if patient.doctor != request.user:
                return Response({"error": "Unauthorized access."}, status=status.HTTP_403_FORBIDDEN)

            serializer = PatientSerializer(patient)
            return Response({
                "username": patient.user.username,
                "patient_data": serializer.data
            }, status=status.HTTP_200_OK)

        except Patient.DoesNotExist:
            return Response({"error": "Patient not found."}, status=status.HTTP_404_NOT_FOUND)
