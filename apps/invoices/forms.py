from django import forms
from django.forms import inlineformset_factory
from django.contrib.auth import get_user_model
from .models import Invoice, InvoiceItem, InvoiceTemplate
from decimal import Decimal

User = get_user_model()


class InvoiceForm(forms.ModelForm):
    DISCOUNT_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount (₦)'),
    ]
    TAX_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount (₦)'),
    ]
    
    tax_type = forms.ChoiceField(
        choices=TAX_TYPE_CHOICES,
        required=False,
        initial='percentage',
        widget=forms.Select(attrs={
            'class': 'form-select type-selector',
            'id': 'tax_type'
        })
    )
    tax_input = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control money-input',
        'placeholder': 'e.g. 7.5 or 7.5%',
        'id': 'tax_input'
    }), label='Tax/VAT')
    discount_type = forms.ChoiceField(
        choices=DISCOUNT_TYPE_CHOICES,
        required=False,
        initial='percentage',
        widget=forms.Select(attrs={
            'class': 'form-select type-selector',
            'id': 'discount_type'
        })
    )
    total_discount = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control money-input',
        'placeholder': 'e.g. 10 or 7.5%',
        'id': 'total_discount'
    }))
    shipping_fee = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control money-input',
        'placeholder': '0.00'
    }))
    other_charges = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control money-input',
        'placeholder': '0.00'
    }))
    amount_paid = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control money-input',
        'placeholder': '0.00'
    }))
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Make all fields optional
        for field_name, field in self.fields.items():
            field.required = False
        
        # Set initial values for form-only fields (tax_input, total_discount)
        # These are CharFields, not model fields, so they need explicit initialization
        if self.instance and self.instance.pk:
            # Tax value
            if self.instance.tax_value:
                self.fields['tax_input'].initial = self.instance.tax_value
            elif self.instance.subtotal and self.instance.subtotal > 0 and self.instance.total_tax > 0:
                tax_percentage = (self.instance.total_tax / self.instance.subtotal) * 100
                self.fields['tax_input'].initial = round(tax_percentage, 2)
            
            # Discount value
            if self.instance.discount_value:
                self.fields['total_discount'].initial = self.instance.discount_value
            elif self.instance.subtotal and self.instance.subtotal > 0 and self.instance.total_discount > 0:
                discount_percentage = (self.instance.total_discount / self.instance.subtotal) * 100
                self.fields['total_discount'].initial = round(discount_percentage, 2)
        
        if user:
            # Filter templates by user and add an empty option
            self.fields['template'].queryset = InvoiceTemplate.objects.filter(user=user)
            self.fields['template'].empty_label = "Choose a template (optional)"
            
            # Set default template if user has one
            if not self.instance.pk:  # Only for new invoices
                default_template = InvoiceTemplate.objects.filter(user=user, is_default=True).first()
                if default_template:
                    self.fields['template'].initial = default_template
    
    class Meta:
        model = Invoice
        fields = [
            'template', 'due_date', 'client_name', 'client_phone', 'client_email', 
            'client_address', 'tax_type', 'discount_type', 
            'shipping_fee', 'other_charges', 'amount_paid', 'notes',
            'tax_input', 'total_discount',
        ]
        widgets = {
            'template': forms.Select(attrs={
                'class': 'form-control',
                'data-toggle': 'tooltip',
                'title': 'Choose a template for colors and styling'
            }),
            'due_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'client_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter client name'
            }),
            'client_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter phone number'
            }),
            'client_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter email address'
            }),
            'client_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter client address'
            }),
            'total_tax': forms.TextInput(attrs={
                'class': 'form-control money-input',
                'placeholder': 'e.g. 7.5 or 7.5%'
            }),
            'total_discount': forms.TextInput(attrs={
                'class': 'form-control money-input',
                'placeholder': 'e.g. 10 or 7.5%'
            }),
            'shipping_fee': forms.TextInput(attrs={
                'class': 'form-control money-input',
                'placeholder': '0.00'
            }),
            'other_charges': forms.TextInput(attrs={
                'class': 'form-control money-input',
                'placeholder': '0.00'
            }),
            'amount_paid': forms.TextInput(attrs={
                'class': 'form-control money-input',
                'placeholder': '0.00'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Additional notes...'
            })
        }
    
    def clean_tax_input(self):
        value = self.cleaned_data.get('total_tax')
        tax_type = self.cleaned_data.get('tax_type', 'percentage')
        
        if value == '' or value is None:
            return Decimal('0')
        
        # Auto-detect type from input if not explicitly set
        if '%' in str(value):
            self.cleaned_data['tax_type'] = 'percentage'
            # Extract the percentage value
            _, detected_type, raw_value = Invoice.parse_number_with_type(value)
            return raw_value  # Return the raw percentage number, not divided
        
        return Invoice.parse_number(value)
    
    def clean_total_discount(self):
        value = self.cleaned_data.get('total_discount')
        discount_type = self.cleaned_data.get('discount_type', 'percentage')
        
        if value == '' or value is None:
            return Decimal('0')
        
        # Auto-detect type from input if not explicitly set
        if '%' in str(value):
            self.cleaned_data['discount_type'] = 'percentage'
            # Extract the percentage value
            _, detected_type, raw_value = Invoice.parse_number_with_type(value)
            return raw_value  # Return the raw percentage number, not divided
        
        return Invoice.parse_number(value)
    
    def clean_shipping_fee(self):
        value = self.cleaned_data.get('shipping_fee')
        if value == '' or value is None:
            return Decimal('0')
        return Invoice.parse_number(value)
    
    def clean_other_charges(self):
        value = self.cleaned_data.get('other_charges')
        if value == '' or value is None:
            return Decimal('0')
        return Invoice.parse_number(value)
    
    def clean_amount_paid(self):
        value = self.cleaned_data.get('amount_paid')
        if value == '' or value is None:
            return Decimal('0')
        return Invoice.parse_number(value)


class InvoiceItemForm(forms.ModelForm):
    product_service = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': ' '
    }))
    description = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': ' '
    }))
    quantity = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': ' '
    }))
    unit_price = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control money-input',
        'placeholder': ' '
    }))
    
    def __init__(self, *args, **kwargs):
        """
        Override default ModelForm behaviour so that quantity and unit_price
        do NOT enforce any minimum value (we want to allow negative numbers).
        """
        from django.core.validators import MinValueValidator
        super().__init__(*args, **kwargs)
        
        # Strip out any built-in "must be >= 0" validators that Django picked up
        # from the model or migrations. We want *any* numeric value to be allowed.
        for field_name in ['quantity', 'unit_price']:
            field = self.fields.get(field_name)
            if not field:
                continue
            field.validators = [
                v for v in field.validators
                if not isinstance(v, MinValueValidator)
            ]

    def clean(self):
        """
        As an extra safety net, remove any residual '>= 0' errors that might
        still be attached to the quantity/unit_price fields.
        """
        cleaned_data = super().clean()
        if 'id' in self._errors:
            self._errors.pop('id', None)
            cleaned_data['id'] = None
        for field_name in ['quantity', 'unit_price']:
            if field_name in self._errors:
                errors = self._errors.get(field_name)
                # Keep all errors except the MinValueValidator message
                filtered = [
                    e for e in errors
                    if 'greater than or equal to 0' not in str(e)
                ]
                if filtered:
                    self._errors[field_name] = filtered
                else:
                    # If that was the only error, drop the field from errors entirely
                    del self._errors[field_name]
        return cleaned_data
    
    class Meta:
        model = InvoiceItem
        fields = ['product_service', 'description', 'quantity', 'unit_price']
    
    def clean_quantity(self):
        value = self.cleaned_data.get('quantity')
        if value == '' or value is None:
            # Also clear display value
            self.cleaned_data['quantity_display'] = ''
            return Decimal('0')
        
        # Preserve the original text so we can show it later in the table
        # while still using the numeric part for calculations.
        self.cleaned_data['quantity_display'] = value
        return Invoice.parse_number(value)
    
    def clean_unit_price(self):
        value = self.cleaned_data.get('unit_price')
        if value == '' or value is None:
            return Decimal('0')
        return Invoice.parse_number(value)


# Custom formset class to handle empty forms better
class BaseInvoiceItemFormSet(forms.BaseInlineFormSet):
    def add_fields(self, form, index):
        """Django uses a ModelChoiceField for the row pk. Save rebuilds every
        line, so stale ids (after a previous rewrite) must not block submit.
        """
        super().add_fields(form, index)
        pk_name = self.model._meta.pk.name
        field = form.fields.get(pk_name)
        initial = getattr(field, 'initial', None) if field else None
        if getattr(form, 'instance', None) and form.instance.pk:
            initial = form.instance.pk
        elif hasattr(initial, 'pk'):
            initial = initial.pk
        form.fields[pk_name] = forms.IntegerField(
            required=False,
            widget=forms.HiddenInput,
            initial=initial,
        )

    def clean(self):
        """Custom validation to allow empty forms - all item fields are optional"""
        super().clean()
        
        # Don't validate if there are already errors
        if any(self.errors):
            return
        
        # Allow invoices with zero items - all fields are optional
        # Just validate individual form data if present
        for form in self.forms:
            # Skip deleted forms
            if self.can_delete and self._should_delete_form(form):
                continue
                
            # Check if form has meaningful data - all fields are optional
            if hasattr(form, 'cleaned_data') and form.cleaned_data:
                # No validation required - all fields are optional
                pass
    
    def _should_delete_form(self, form):
        """Check if form should be deleted"""
        try:
            return form.cleaned_data.get('DELETE', False)
        except AttributeError:
            return False

# Formset for invoice items
InvoiceItemFormSet = inlineformset_factory(
    Invoice, 
    InvoiceItem,
    form=InvoiceItemForm,
    formset=BaseInvoiceItemFormSet,
    extra=1,  # Always provide one extra form for new items
    min_num=0,  # Allow invoices with no items temporarily
    validate_min=False,  # Don't enforce minimum during save
    can_delete=True,
    max_num=None,  # Allow unlimited items
    exclude=()  # Don't exclude any fields
)


class InvoiceFilterForm(forms.Form):
    # Custom status choices for search filter with user-friendly labels
    STATUS_CHOICES = [
        ('', 'All Status'),
        ('unpaid', 'Not Paid'),
        ('partial', 'Pending'),
        ('paid', 'Paid'),
        ('delivered', 'Delivered'),
    ]
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search invoices...'
        })
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
    # Admin-only: filter by creator (team member). Queryset set in view when is_company_admin.
    created_by = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label='All team members',
        label='Created by',
        widget=forms.Select(attrs={'class': 'form-control'})
    )


class InvoiceTemplateForm(forms.ModelForm):
    """Form for creating and editing invoice templates"""
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean_name(self):
        name = self.cleaned_data.get('name')
        if self.user and name:
            # Check if another template with this name exists for this user
            existing = InvoiceTemplate.objects.filter(user=self.user, name=name)
            # Exclude current instance if editing
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise forms.ValidationError(f'You already have a template named "{name}". Please choose a different name.')
        
        return name
    
    class Meta:
        model = InvoiceTemplate
        fields = [
            'name', 'description', 'primary_color', 'secondary_color', 
            'text_color', 'accent_color', 'show_company_logo', 'show_company_details',
            'show_bank_details', 'show_signature', 'document_title', 'number_prefix',
            'default_payment_terms', 'footer_text', 'is_default'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter template name (e.g., Professional Invoice)'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional description of this template'
            }),
            'primary_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'title': 'Choose primary color'
            }),
            'secondary_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'title': 'Choose secondary color'
            }),
            'text_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'title': 'Choose text color'
            }),
            'accent_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'title': 'Choose accent color'
            }),
            'show_company_logo': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'show_company_details': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'show_bank_details': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'show_signature': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'document_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'INVOICE'
            }),
            'number_prefix': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'INV',
                'maxlength': 10
            }),
            'default_payment_terms': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Payment due within 30 days'
            }),
            'footer_text': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Thank you for your business!'
            }),
            'is_default': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
