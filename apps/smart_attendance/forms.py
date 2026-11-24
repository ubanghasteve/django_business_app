from django import forms

from .models import BiometricDevice, Employee


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "employee_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "department",
            "position",
            "biometric_uid",
            "profile_photo",
            "is_active",
        ]
        widgets = {
            "employee_id": forms.TextInput(attrs={"placeholder": "e.g. EMP001"}),
            "first_name": forms.TextInput(attrs={"placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Last name"}),
            "email": forms.EmailInput(attrs={"placeholder": "email@example.com"}),
            "phone": forms.TextInput(attrs={"placeholder": "+2348012345678"}),
            "department": forms.TextInput(attrs={"placeholder": "e.g. Engineering"}),
            "position": forms.TextInput(attrs={"placeholder": "e.g. Software Engineer"}),
            "biometric_uid": forms.TextInput(attrs={"placeholder": "UID from biometric device"}),
        }

    def clean_employee_id(self):
        val = self.cleaned_data.get("employee_id")
        if val:
            val = str(val).strip()
        return val

    def clean_email(self):
        val = self.cleaned_data.get("email")
        if val:
            val = str(val).strip().lower()
        return val


class BiometricDeviceForm(forms.ModelForm):
    class Meta:
        model = BiometricDevice
        fields = [
            "device_name",
            "device_serial",
            "device_ip",
            "device_port",
            "device_model",
            "firmware_version",
            "device_secret",
            "location",
        ]
        help_texts = {
            "device_name": "A friendly name for this device (e.g. 'Reception Kiosk').",
            "device_serial": "Exact serial number from your ZKTeco device (Device Info screen or ZKAccess). Must match exactly what the device sends in push requests.",
            "device_ip": "IP address of the biometric machine on your network (e.g. 192.168.1.100). Leave blank for push-only (device pushes to this app).",
            "device_port": "ZKTeco default is 4370.",
            "device_secret": "Shared secret for push authentication. Set this EXACT value in the device firmware; the device sends it via X-Device-Secret header or device_secret in the request body.",
        }
        widgets = {
            "device_ip": forms.TextInput(attrs={"placeholder": "e.g. 192.168.1.100 or leave blank for push-only"}),
            "device_serial": forms.TextInput(attrs={"placeholder": "Exact serial as shown on device"}),
            "device_secret": forms.PasswordInput(attrs={"placeholder": "Same value as in device firmware"}, render_value=True),
        }

    def clean_device_serial(self):
        val = self.cleaned_data.get("device_serial")
        if val:
            val = str(val).strip()
            if not val:
                raise forms.ValidationError("Device serial is required.")
            # Check duplicate (model has unique=True on device_serial)
            qs = BiometricDevice.objects.filter(device_serial=val)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "A device with this serial is already registered. Use the exact serial your ZKTeco device sends in push requests."
                )
        return val

    def clean_device_secret(self):
        val = self.cleaned_data.get("device_secret")
        if val:
            val = str(val).strip()
            if not val:
                raise forms.ValidationError("Device secret is required for push authentication.")
        return val

    def clean_device_name(self):
        val = self.cleaned_data.get("device_name")
        val = str(val).strip() if val else ""
        if not val:
            raise forms.ValidationError("Device name is required.")
        return val

    def clean_device_ip(self):
        """Allow blank for push-only devices; store as None."""
        val = self.cleaned_data.get("device_ip")
        if val is None or (isinstance(val, str) and not val.strip()):
            return None
        return val

    def clean_device_port(self):
        """Ensure port is valid; ZKTeco default 4370."""
        val = self.cleaned_data.get("device_port")
        if val is not None and (val < 1 or val > 65535):
            raise forms.ValidationError("Port must be between 1 and 65535.")
        return val or 4370

