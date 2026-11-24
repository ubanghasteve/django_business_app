from django import forms
from .models import Product, Order, Receipt, Waybill, ProductStatusHistory
from apps.accounts.models import User
from .models import Leave, Customer, Store, StoreInventory, StockMovement, Invoice
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils import timezone

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        exclude = ['approved_by', 'approval_status', 'created_by', 'updated_by', 'production_status', 'name', 'cycle_time']
        
        fields = [
            # job_order is auto-generated (unique 3-digit serial), not in form
            'job_order_date',      # Job Order Date (optional - first on form)
            'organization_name',    # Job Name
            'address',             # Customer Name
            'contact_number',      # Contact Number (Phone)
            'print_product',       # Package Type/Product
            'colors',              # No. of Colors/Color Names
            'treatment',           # Treatment
            'cutting_length',      # Cutting Length
            'flap',                # Flap
            'printing',            # Printing
            'order_info',          # Order Info
            'size',                # Thickness
            'micron',              # Micron
            'width',               # Width
            'sealing_type',        # Sealing Type
            'cutting',             # Cutting
            'gusset',              # Gusset
            'price',               # Price (₦)
            'job_title',           # Extrusion Quantity
            'order_quantity',      # Delivery Quantity
            'estimated_delivery_date',  # Estimated Delivery Date
            'actual_delivery_date',     # Actual Delivery Date
            'image', 
        ]
        
        labels = {
            'organization_name': 'Job Name',
            'address': 'Customer Name',
            'contact_number': 'Contact Number (Phone)',
            'print_product': 'Package Type/Product',
            'colors': 'No. of Colors/Color Names',
            'treatment': 'Treatment',
            'cutting_length': 'Cutting Length',
            'flap': 'Flap',
            'printing': 'Printing',
            'order_info': 'Order Information',
            'size': 'Thickness',
            'micron': 'Micron',
            'width': 'Width',
            'sealing_type': 'Sealing Type',
            'cutting': 'Cutting',
            'gusset': 'Gusset',
            'price': 'Price',  # Set in __init__ with company currency symbol
            'job_title': 'Extrusion Quantity (kg)',
            'order_quantity': 'Delivery Quantity (kg)',
            'job_order_date': 'Job Order Date',
            'estimated_delivery_date': 'Estimated Delivery Date',
            'actual_delivery_date': 'Actual Delivery Date',
            'image': 'Upload Image',
        }

        widgets = {
            'organization_name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'print_product': forms.TextInput(attrs={'class': 'form-control'}),
            'size': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_number': forms.TextInput(attrs={'class': 'form-control'}),
            'treatment': forms.TextInput(attrs={'class': 'form-control'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control'}),
            'printing': forms.TextInput(attrs={'class': 'form-control'}),
            'colors': forms.TextInput(attrs={'class': 'form-control'}),
            'order_info': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'cutting_length': forms.TextInput(attrs={'class': 'form-control'}),
            'micron': forms.TextInput(attrs={'class': 'form-control'}),
            'width': forms.TextInput(attrs={'class': 'form-control'}),
            'sealing_type': forms.TextInput(attrs={'class': 'form-control'}),
            'cutting': forms.TextInput(attrs={'class': 'form-control'}),
            'gusset': forms.TextInput(attrs={'class': 'form-control'}),
            'flap': forms.TextInput(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={
                'id': 'id_price',
                'step': '0.01',
                'class': 'form-control'
            }),
            'order_quantity': forms.TextInput(attrs={
                'id': 'id_order_quantity',
                'class': 'form-control',
                'placeholder': 'e.g. 100, 100 kg, 50+50'
            }),
            'job_order_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
                'placeholder': 'Optional'
            }),
            'estimated_delivery_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'actual_delivery_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'image': forms.ClearableFileInput(attrs={
                'accept': 'image/*',
                'class': 'form-control',
                'id': 'id_image'
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        currency_symbol = kwargs.pop('currency_symbol', None)
        super(ProductForm, self).__init__(*args, **kwargs)
        
        self.fields['image'].required = False
        self.fields['job_order_date'].required = False
        if currency_symbol is not None:
            self.fields['price'].label = f'Price ({currency_symbol})'
        else:
            self.fields['price'].label = 'Price (₦)'
        
        if user and user.is_superuser:
            self.fields['approval_status'] = forms.ChoiceField(
                choices=[('pending', 'Pending'), ('approve', 'Approve'), ('deny', 'Deny')],
                required=True,
                widget=forms.Select(attrs={'class': 'form-control'})
            )
            self.fields['approved_by'] = forms.ModelChoiceField(
                queryset=User.objects.filter(is_superuser=True),
                required=False,
                widget=forms.Select(attrs={'class': 'form-control'})
            )
            self.fields['created_by'] = forms.ModelChoiceField(
                queryset=User.objects.all(),
                required=False,
                widget=forms.Select(attrs={'class': 'form-control'})
            )

class LeaveForm(forms.ModelForm):
    duration = forms.IntegerField(disabled=True, required=False)
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if start_date and end_date:
            if start_date > end_date:
                raise forms.ValidationError("End date must be after start date")
            
            # Calculate duration
            duration = (end_date - start_date).days + 1
            cleaned_data['duration'] = duration
            
            # Check maximum leave duration
            if duration > 30:
                raise forms.ValidationError("Leave duration cannot exceed 30 days")
        
        return cleaned_data
    
    class Meta:
        model = Leave
        fields = ['leave_type', 'start_date', 'end_date', 'reason']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

class LeaveResponseForm(forms.ModelForm):
    class Meta:
        model = Leave
        fields = ['status', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Enter response message'}),
            'status': forms.Select(choices=[
                ('approved', 'Approve'),
                ('rejected', 'Reject'),
                ('pending', 'Pending')
            ])
        }

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'email', 'phone', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class StoreForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = ['name', 'location', 'manager']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'manager': forms.Select(attrs={'class': 'form-control'}),
        }

class StoreInventoryForm(forms.ModelForm):
    class Meta:
        model = StoreInventory
        fields = ['store', 'product', 'quantity', 'reorder_level']
        widgets = {
            'store': forms.Select(attrs={'class': 'form-control'}),
            'product': forms.Select(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'reorder_level': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }

class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = ['store', 'product', 'movement_type', 'quantity', 'reference', 'notes']
        widgets = {
            'store': forms.Select(attrs={'class': 'form-control'}),
            'product': forms.Select(attrs={'class': 'form-control'}),
            'movement_type': forms.Select(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'reference': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class WaybillForm(forms.ModelForm):
    class Meta:
        model = Waybill
        fields = ['customer', 'product', 'quantity', 'origin', 'destination', 'notes']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-control'}),
            'product': forms.Select(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'origin': forms.TextInput(attrs={'class': 'form-control'}),
            'destination': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class ReceiptForm(forms.ModelForm):
    class Meta:
        model = Receipt
        fields = ['customer', 'product', 'amount', 'payment_method', 'notes']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-control'}),
            'product': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'payment_method': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['customer', 'product', 'amount', 'tax_rate', 'due_date', 'notes']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-control'}),
            'product': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'tax_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['product', 'customer', 'order_quantity', 'estimated_delivery_date', 'additional_notes']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control'}),
            'customer': forms.Select(attrs={'class': 'form-control'}),
            'order_quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'estimated_delivery_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'additional_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class ProductStatusHistoryForm(forms.ModelForm):
    class Meta:
        model = ProductStatusHistory
        fields = ['status', 'priority']
        widgets = {
            'status': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'priority': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }
