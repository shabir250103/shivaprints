from decimal import Decimal
from pathlib import Path

from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from rest_framework import serializers
from PIL import Image, UnidentifiedImageError

_UNSET = object()

from .models import (
    Branch,
    Supplier, FinanceEntry, Quotation,
    CompanySettings,
    Customer,
    CustomerPayment,
    CustomerType,
    CashAccount,
    CashTransaction,
    CashTransfer,
    Delivery,
    Department,
    FollowUp,
    InJob,
    InJobDropdownOption,
    Invoice,
    JobPriority,
    JobDocument,
    Machine,
    MachineCounter,
    MachineStatusHistory,
    ModulePermissionOverride,
    Notification,
    OutJob,
    PaymentStatus,
    PipelineJob,
    StockCategory,
    StockItem,
    StockMovement,
    Role,
    UserProfile,
    WastageRecord,
    VendorPayment,
)
from .permissions import user_has_module_access, check_user_management, check_permission_grant


class QuotationItemSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=500)
    quantity = serializers.DecimalField(max_digits=9, decimal_places=2, min_value=Decimal('0.01'))
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0'))


class QuotationSerializer(serializers.ModelSerializer):
    items = QuotationItemSerializer(many=True, allow_empty=False)
    quotation_number = serializers.CharField(read_only=True)
    totals = serializers.SerializerMethodField()
    grand_total = serializers.SerializerMethodField()

    class Meta:
        model = Quotation
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at', 'branch')

    def get_totals(self, obj):
        return {key: format(value, '.2f') for key, value in obj.totals.items()}

    def get_grand_total(self, obj):
        return format(obj.totals['grand_total'], '.2f')

    def validate_items(self, items):
        if len(items) > 100:
            raise serializers.ValidationError('Use no more than 100 line items.')
        return [{key: str(value) for key, value in item.items()} for item in items]

    def validate_source_enquiry(self, enquiry):
        request = self.context.get('request')
        if enquiry and request and not user_has_module_access(request.user, 'followups'):
            raise serializers.ValidationError('Enquiry access is required to convert an enquiry to a quotation.')
        return enquiry

    def validate(self, attrs):
        from decimal import ROUND_HALF_UP
        value = lambda key, default: attrs.get(key, getattr(self.instance, key, default))
        items = value('items', [])
        subtotal = sum(((Decimal(item['quantity']) * Decimal(item['unit_price'])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) for item in items), Decimal('0'))
        discount = value('discount', Decimal('0'))
        if not 0 <= discount <= subtotal:
            raise serializers.ValidationError({'discount': 'Discount must be between zero and subtotal.'})
        if not 0 <= value('gst_percent', Decimal('18')) <= 100:
            raise serializers.ValidationError({'gst_percent': 'GST percentage must be between 0 and 100.'})
        valid_until = value('valid_until', None)
        from django.utils import timezone
        if valid_until and valid_until < value('quotation_date', timezone.localdate()):
            raise serializers.ValidationError({'valid_until': 'Validity cannot end before the quotation date.'})
        return attrs


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class BranchSerializer(serializers.ModelSerializer):
    manager_name = serializers.CharField(source='manager.get_full_name', read_only=True)
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Branch
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at', 'user_count')

    def validate_manager(self, value):
        if value and not value.is_active:
            raise serializers.ValidationError('The branch manager must be active.')
        return value

    def get_user_count(self, obj):
        return obj.users.count()


class FinanceEntrySerializer(serializers.ModelSerializer):
    account = serializers.PrimaryKeyRelatedField(queryset=CashAccount.objects.filter(is_active=True))
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.filter(is_active=True), required=False, allow_null=True)
    account_name = serializers.CharField(source='account.name', read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    balance_after = serializers.DecimalField(source='cash_transaction.balance_after', max_digits=14, decimal_places=2, read_only=True)
    request_key = serializers.UUIDField()

    class Meta:
        model = FinanceEntry
        fields = '__all__'
        read_only_fields = ('cash_transaction', 'created_by', 'created_at', 'updated_at')

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ('id', 'name', 'slug', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('slug', 'created_at', 'updated_at')


class CustomerTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerType
        fields = ('id', 'name', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('created_at', 'updated_at')


class CustomerSerializer(serializers.ModelSerializer):
    customer_type_name = serializers.CharField(source='customer_type.name', read_only=True)

    class Meta:
        model = Customer
        fields = (
            'id', 'name', 'mobile', 'email', 'gst_number', 'address',
            'billing_address', 'delivery_address', 'notes', 'customer_type',
            'customer_type_name', 'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = ('created_at', 'updated_at')

    def validate_gst_number(self, value):
        value = value.strip().upper()
        if value and len(value) != 15:
            raise serializers.ValidationError('GST number must contain exactly 15 characters.')
        return value


class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = (
            'id', 'code', 'name', 'location', 'operational_status',
            'status_reason', 'is_default', 'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = ('created_at', 'updated_at')

    def validate(self, attrs):
        status = attrs.get('operational_status', getattr(self.instance, 'operational_status', Machine.OperationalStatus.RUNNING))
        reason = attrs.get('status_reason', getattr(self.instance, 'status_reason', ''))
        if status in {Machine.OperationalStatus.STOPPED, Machine.OperationalStatus.BREAKDOWN} and not reason.strip():
            raise serializers.ValidationError({'status_reason': 'A reason is required when a machine is stopped or in breakdown.'})
        return attrs


class StockCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = StockCategory
        fields = ('id', 'name', 'is_active', 'created_at')
        read_only_fields = ('created_at',)

    def validate_name(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError('Category name cannot be empty.')
        return val


class StockItemSerializer(serializers.ModelSerializer):
    is_low_stock = serializers.BooleanField(read_only=True)
    category = serializers.CharField(max_length=100, default='Paper')

    class Meta:
        model = StockItem
        fields = (
            'id', 'name', 'category', 'color', 'gsm', 'size', 'current_stock',
            'min_stock', 'unit', 'is_low_stock', 'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = ('created_at', 'updated_at', 'is_low_stock')

    def validate_category(self, value):
        cat = (value or '').strip()
        if cat:
            StockCategory.objects.get_or_create(name=cat)
        return cat or 'Paper'

    def validate(self, attrs):
        if self.instance and 'current_stock' in attrs and attrs['current_stock'] != self.instance.current_stock:
            raise serializers.ValidationError({'current_stock': 'Use the stock adjustment endpoint to change current stock.'})
        return attrs


class PipelineJobSerializer(serializers.ModelSerializer):
    customer_display = serializers.CharField(source='customer.name', read_only=True)
    designer_display = serializers.CharField(source='assigned_designer.get_full_name', read_only=True)
    reference_image = serializers.ImageField(write_only=True, required=False)
    has_reference_image = serializers.SerializerMethodField()
    reference_files = serializers.ListField(child=serializers.FileField(), write_only=True, required=False)
    reference_documents = serializers.SerializerMethodField()

    def validate_source_enquiry(self, enquiry):
        request = self.context.get('request')
        if enquiry and request and not user_has_module_access(request.user, 'followups'):
            raise serializers.ValidationError('Enquiry access is required to convert an enquiry to a pipeline job.')
        return enquiry

    def get_has_reference_image(self, job):
        return bool(job.reference_image)

    def validate_reference_image(self, image):
        if image.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('Reference image must be 10 MB or smaller.')
        return image

    def get_reference_documents(self, job):
        return [
            {'id': document.pk, 'name': document.original_name or Path(document.file.name).name}
            for document in job.documents.filter(kind=JobDocument.Kind.REFERENCE)
        ]

    def validate_reference_files(self, files):
        for uploaded in files:
            extension = Path(uploaded.name).suffix.lower()
            if extension not in {'.pdf', '.jpg', '.jpeg', '.png'}:
                raise serializers.ValidationError('Only PDF, JPG, JPEG, and PNG files are allowed.')
            if uploaded.size > 10 * 1024 * 1024:
                raise serializers.ValidationError('Each reference file must be 10 MB or smaller.')
            if extension == '.pdf':
                if uploaded.read(5) != b'%PDF-':
                    raise serializers.ValidationError('The selected PDF file is invalid.')
            else:
                try:
                    with Image.open(uploaded) as image:
                        image.verify()
                except (OSError, UnidentifiedImageError) as exc:
                    raise serializers.ValidationError('The selected image file is invalid.') from exc
            uploaded.seek(0)
        return files

    @transaction.atomic
    def create(self, validated_data):
        files = validated_data.pop('reference_files', [])
        job = super().create(validated_data)
        self._save_reference_files(job, files)
        return job

    @transaction.atomic
    def update(self, instance, validated_data):
        files = validated_data.pop('reference_files', [])
        job = super().update(instance, validated_data)
        self._save_reference_files(job, files)
        return job

    def _save_reference_files(self, job, files):
        for uploaded in files:
            JobDocument.objects.create(
                pipeline_job=job, kind=JobDocument.Kind.REFERENCE,
                file=uploaded, original_name=uploaded.name,
                uploaded_by=self.context['request'].user,
            )

    class Meta:
        model = PipelineJob
        fields = (
            'id', 'job_number', 'customer', 'customer_display', 'source_enquiry', 'client_name',
            'contact_number', 'job_date', 'job_type', 'size', 'quantity',
            'printing_method', 'reference_image', 'has_reference_image', 'reference_files', 'reference_documents',
            'quote', 'priority', 'status', 'assigned_designer',
            'designer_display', 'remarks', 'created_by', 'created_at', 'updated_at',
        )
        read_only_fields = ('job_number', 'created_by', 'created_at', 'updated_at', 'has_reference_image', 'reference_documents')


OPTION_FIELD_MAPPING = (
    ('priority_option', InJobDropdownOption.Field.PRIORITY, 'priority'),
    ('side_option', InJobDropdownOption.Field.SIDE_MODE, 'side_mode'),
    ('payment_option', InJobDropdownOption.Field.PAYMENT_STATUS, 'payment_status'),
)


def apply_in_job_option_aliases(attrs):
    for option_key, expected_field, canonical_key in OPTION_FIELD_MAPPING:
        option = attrs.get(option_key)
        if option:
            if not option.is_active or option.field_name != expected_field:
                raise serializers.ValidationError({option_key: 'This option does not belong to the selected field.'})
            attrs[canonical_key] = option.base_value
    return attrs


class InJobDropdownOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = InJobDropdownOption
        fields = ('id', 'field_name', 'label', 'base_value', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('created_at', 'updated_at')

    def validate(self, attrs):
        field_name = attrs.get('field_name', getattr(self.instance, 'field_name', None))
        base_value = attrs.get('base_value', getattr(self.instance, 'base_value', ''))
        allowed = {
            InJobDropdownOption.Field.PRIORITY: {'low', 'normal', 'high', 'urgent'},
            InJobDropdownOption.Field.SIDE_MODE: {'SS', 'DS'},
            InJobDropdownOption.Field.PAYMENT_STATUS: {'unpaid', 'partial', 'paid'},
        }
        if field_name in allowed and base_value not in allowed[field_name]:
            raise serializers.ValidationError({'base_value': 'Choose which built-in workflow value this option behaves like.'})
        if field_name not in allowed and base_value:
            raise serializers.ValidationError({'base_value': 'A base workflow value is only used for Priority, Side, and Payment Status.'})
        return attrs


def validate_job_finance(attrs, instance=None, *, vendor=False):
    pairs = [('total_amount', 'advance', 'payment_status')]
    if vendor:
        pairs.append(('vendor_total_payment', 'vendor_advance', 'vendor_payment_status'))
    for total_field, paid_field, status_field in pairs:
        total = attrs.get(total_field, getattr(instance, total_field, Decimal('0')))
        paid = attrs.get(paid_field, getattr(instance, paid_field, Decimal('0')))
        if instance:
            for field in (paid_field, status_field):
                if field in attrs and attrs[field] != getattr(instance, field):
                    raise serializers.ValidationError({field: 'Use the payment workflow to change posted payments.'})
        if total < 0 or paid < 0 or paid > total:
            raise serializers.ValidationError({total_field: 'Total must be non-negative and cannot be less than posted payments.'})
        if instance and total_field == 'total_amount' and total != instance.total_amount:
            delivery = getattr(instance, 'delivery', None)
            if delivery and delivery.status in {Delivery.Status.DISPATCHED, Delivery.Status.DELIVERED}:
                raise serializers.ValidationError({total_field: 'The customer total cannot change after dispatch.'})
        canonical = PaymentStatus.PAID if paid and paid == total else PaymentStatus.PARTIAL if paid else PaymentStatus.UNPAID
        attrs[status_field] = canonical
    if not vendor:
        option = attrs.get('payment_option', getattr(instance, 'payment_option', None))
        if option and option.base_value != attrs['payment_status']:
            attrs['payment_option'] = None
    return attrs


class InJobSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    profit = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    assigned_staff_display = serializers.SerializerMethodField()
    created_by_display = serializers.SerializerMethodField()
    accepted_by_display = serializers.SerializerMethodField()
    delivery_status = serializers.SerializerMethodField()
    designer_display = serializers.SerializerMethodField()
    invoice_id = serializers.SerializerMethodField()
    invoice_no = serializers.SerializerMethodField()
    machine_name = serializers.SerializerMethodField()
    printing_operator_display = serializers.SerializerMethodField()
    wastage_operator_display = serializers.SerializerMethodField()
    current_count = serializers.IntegerField(read_only=True)
    priority_label = serializers.SerializerMethodField()
    side_label = serializers.SerializerMethodField()
    payment_label = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()
    payment_method_input = serializers.CharField(write_only=True, required=False, allow_blank=True)
    cash_account = serializers.PrimaryKeyRelatedField(queryset=CashAccount.objects.filter(is_active=True), write_only=True, required=False, allow_null=True)
    everyone_in_department = serializers.PrimaryKeyRelatedField(queryset=Department.active.all(), write_only=True, required=False, allow_null=True)

    def get_payment_method(self, job):
        payments = list(job.payments.all())
        return payments[0].method if payments else ''

    def get_assigned_staff_display(self, job):
        return ', '.join(user.get_full_name() or user.username for user in job.assigned_users.all())

    def get_created_by_display(self, job):
        return job.created_by.get_full_name() or job.created_by.username

    def get_accepted_by_display(self, job):
        return (job.accepted_by.get_full_name() or job.accepted_by.username) if job.accepted_by_id else ''

    def get_delivery_status(self, job):
        delivery = getattr(job, 'delivery', None)
        return delivery.status if delivery else None

    def get_invoice_id(self, job):
        try:
            inv = getattr(job, 'invoice', None)
            return inv.id if inv else None
        except Exception:
            return None

    def get_invoice_no(self, job):
        try:
            inv = getattr(job, 'invoice', None)
            return inv.invoice_no if inv else None
        except Exception:
            return None

    def get_designer_display(self, job):
        return (job.designer.get_full_name() or job.designer.username) if job.designer_id else ''

    def get_machine_name(self, job):
        return job.machine.name if job.machine_id else ''

    def get_printing_operator_display(self, job):
        return (job.printing_operator.get_full_name() or job.printing_operator.username) if job.printing_operator_id else ''

    def get_wastage_operator_display(self, job):
        return (job.wastage_operator.get_full_name() or job.wastage_operator.username) if job.wastage_operator_id else ''

    def get_priority_label(self, job):
        return job.priority_option.label if job.priority_option_id else job.get_priority_display()

    def get_side_label(self, job):
        return job.side_option.label if job.side_option_id else job.side_mode

    def get_payment_label(self, job):
        return job.payment_option.label if job.payment_option_id else job.get_payment_status_display()

    class Meta:
        model = InJob
        fields = '__all__'
        read_only_fields = ('job_number', 'created_by', 'created_at', 'updated_at', 'balance', 'profit', 'current_count', 'click_count', 'accepted_by', 'accepted_at', 'work_started_at', 'delivery_status', 'branch')
        extra_kwargs = {
            'customer_name': {'required': False, 'allow_blank': True},
            'job_type': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        apply_in_job_option_aliases(attrs)
        if not self.instance:
            from .services import parse_in_job_name
            parsed = parse_in_job_name(attrs.get('job_name', ''))
            pipeline = attrs.get('pipeline_job')
            request = self.context.get('request')
            if pipeline and request and not user_has_module_access(request.user, 'pipeline'):
                raise serializers.ValidationError({'pipeline_job': 'Pipeline permission is required to link a pipeline job.'})
            if pipeline and pipeline.status == PipelineJob.Status.CANCELLED:
                raise serializers.ValidationError({'pipeline_job': 'A cancelled pipeline job cannot be linked.'})
            customer = attrs.get('customer') or (pipeline.customer if pipeline else None)
            if not (attrs.get('customer_name') or (customer and customer.name) or parsed.get('customer_name') or (pipeline and pipeline.client_name)):
                raise serializers.ValidationError({'customer_name': 'Enter a customer name, select a customer, or use a parseable job name.'})
            if not (attrs.get('job_type') or (pipeline and pipeline.job_type)):
                raise serializers.ValidationError({'job_type': 'Job type is required.'})
            if attrs.get('advance', 0) > attrs.get('total_amount', 0):
                raise serializers.ValidationError({'advance': 'Advance cannot exceed the total amount.'})
        wastage_count = attrs.get('wastage_count', self.instance.wastage_count if self.instance else 0)
        wastage_operator = attrs.get('wastage_operator', self.instance.wastage_operator if self.instance else None)
        if wastage_count > 0 and not wastage_operator:
            raise serializers.ValidationError({'wastage_operator': 'Select the employee responsible for the wastage.'})
        if attrs.get('printing_status') == InJob.ProductionStatus.IN_PROGRESS and not (self.instance and self.instance.printing_status == InJob.ProductionStatus.IN_PROGRESS):
            raise serializers.ValidationError({'printing_status': 'Accept and start this job from the job board first.'})
        printing = attrs.get('printing_status', self.instance.printing_status if self.instance else InJob.ProductionStatus.PENDING)
        finishing = attrs.get('finishing_status', self.instance.finishing_status if self.instance else InJob.ProductionStatus.PENDING)
        if printing == InJob.ProductionStatus.COMPLETED and not (self.instance and self.instance.work_started_at):
            raise serializers.ValidationError({'printing_status': 'Start work before completing printing.'})
        if finishing == InJob.ProductionStatus.COMPLETED:
            if printing != InJob.ProductionStatus.COMPLETED:
                raise serializers.ValidationError({'finishing_status': 'Complete printing before completing finishing.'})
            if not (self.instance and self.instance.work_started_at):
                raise serializers.ValidationError({'finishing_status': 'Start work before completing finishing.'})
        if self.instance and self.instance.printing_status == InJob.ProductionStatus.COMPLETED and self.instance.finishing_status == InJob.ProductionStatus.COMPLETED and (printing != InJob.ProductionStatus.COMPLETED or finishing != InJob.ProductionStatus.COMPLETED):
            raise serializers.ValidationError('A completed job has already moved to delivery and cannot be reopened.')
        return validate_job_finance(attrs, self.instance)

    @transaction.atomic
    def create(self, validated_data):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from .services import convert_pipeline_to_in_job, parse_in_job_name, initialize_job_finance, post_opening_advances

        department = validated_data.pop('everyone_in_department', None)
        departments = validated_data.pop('assigned_departments', [])
        pipeline = validated_data.pop('pipeline_job', None)
        user = validated_data.pop('created_by')
        if pipeline:
            try:
                job = convert_pipeline_to_in_job(pipeline, user, **validated_data, everyone_in_department=department)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(getattr(exc, 'message_dict', None) or exc.messages) from exc
        else:
            customer = validated_data.get('customer')
            stock = validated_data.get('stock_item')
            values = {'gst_percent': Decimal('18.00')}
            values.update(parse_in_job_name(validated_data.get('job_name', '')))
            if customer:
                values.update(customer_name=customer.name, contact_number=customer.mobile)
            if stock:
                values.update(paper_type=stock.name, gsm=stock.gsm, paper_size=stock.size)
            values.update({key: value for key, value in validated_data.items() if value is not None and value != ''})
            if not values.get('designer') and values.get('job_initials'):
                from django.contrib.auth import get_user_model
                from django.db.models import Q
                User = get_user_model()
                init = str(values['job_initials']).strip().lower()
                matched_designer = User.objects.filter(is_active=True).filter(
                    Q(username__iexact=init) |
                    Q(first_name__iexact=init) |
                    Q(last_name__iexact=init)
                ).first()
                if matched_designer:
                    values['designer'] = matched_designer
            if not values.get('machine'):
                values['machine'] = Machine.active.filter(is_default=True).first()
            values['click_count'] = InJob.calculate_click_count(values.get('sheet_count', 0), values.get('side_mode', 'SS'))
            assigned_users = values.pop('assigned_users', [])
            cust_method = values.pop('payment_method_input', values.pop('payment_method', 'Petty Cash'))
            cust_account = values.pop('cash_account', None)
            advances = initialize_job_finance(values)
            job = InJob.objects.create(created_by=user, **values)
            post_opening_advances(job, user, advances, cash_account=cust_account, method=cust_method)
            if assigned_users:
                job.assigned_users.set(assigned_users)
        if departments:
            job.assigned_departments.add(*departments)
        if department:
            job.assigned_departments.add(department)
        return job

    def update(self, instance, validated_data):
        validated_data.pop('payment_method_input', None)
        validated_data.pop('cash_account', None)
        validated_data.pop('everyone_in_department', None)
        for option_key, _expected_field, canonical_key in OPTION_FIELD_MAPPING:
            if canonical_key in validated_data and option_key not in validated_data:
                validated_data[option_key] = None
        if {'sheet_count', 'side_mode'}.intersection(validated_data):
            sheet_count = validated_data.get('sheet_count', instance.sheet_count)
            side_mode = validated_data.get('side_mode', instance.side_mode)
            validated_data['click_count'] = InJob.calculate_click_count(sheet_count, side_mode)
        return super().update(instance, validated_data)

    IN_JOB_FINANCE_FIELDS = frozenset((
        'total_amount', 'advance', 'balance', 'expenses', 'profit', 'payment_status',
        'invoice_no', 'gst_percent', 'payment_method', 'payment_label',
    ))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request and not request.user.is_superuser:
            profile = getattr(request.user, 'libin_profile', None)
            if profile and not profile.show_payment_details:
                for field in self.IN_JOB_FINANCE_FIELDS:
                    data.pop(field, None)
        return data


class OutJobSerializer(serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.filter(is_active=True), required=False, allow_null=True)
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    profit = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    vendor_balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    supplier_expenses = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    assigned_staff_display = serializers.SerializerMethodField()
    created_by_display = serializers.SerializerMethodField()
    accepted_by_display = serializers.SerializerMethodField()
    delivery_status = serializers.SerializerMethodField()
    invoice_id = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()
    customer_payment_method = serializers.CharField(write_only=True, required=False, allow_blank=True)
    customer_cash_account = serializers.PrimaryKeyRelatedField(queryset=CashAccount.objects.filter(is_active=True), write_only=True, required=False, allow_null=True)
    vendor_payment_method = serializers.CharField(write_only=True, required=False, allow_blank=True)
    vendor_cash_account = serializers.PrimaryKeyRelatedField(queryset=CashAccount.objects.filter(is_active=True), write_only=True, required=False, allow_null=True)

    def get_payment_method(self, job):
        payments = list(job.payments.all())
        return payments[0].method if payments else ''

    def get_assigned_staff_display(self, job):
        return ', '.join(user.get_full_name() or user.username for user in job.assigned_users.all())

    def get_created_by_display(self, job):
        return job.created_by.get_full_name() or job.created_by.username

    def get_accepted_by_display(self, job):
        return (job.accepted_by.get_full_name() or job.accepted_by.username) if job.accepted_by_id else ''

    def get_delivery_status(self, job):
        delivery = getattr(job, 'delivery', None)
        return delivery.status if delivery else None

    def get_invoice_id(self, job):
        try:
            inv = getattr(job, 'invoice', None)
            return inv.id if inv else None
        except Exception:
            return None

    def get_invoice_no(self, job):
        try:
            inv = getattr(job, 'invoice', None)
            return inv.invoice_no if inv else None
        except Exception:
            return None

    ADMIN_FIELDS = frozenset((
        'total_amount', 'advance', 'balance', 'expenses', 'profit', 'payment_status',
        'invoice_no', 'gst_percent', 'vendor_total_payment', 'vendor_advance',
        'vendor_balance', 'vendor_payment_status', 'payment_method',
    ))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request and not request.user.is_superuser:
            profile = getattr(request.user, 'libin_profile', None)
            if profile and not profile.show_payment_details:
                for field in self.ADMIN_FIELDS:
                    data.pop(field, None)
        return data

    class Meta:
        model = OutJob
        fields = '__all__'
        extra_kwargs = {'customer_name': {'required': False, 'allow_blank': True}}
        read_only_fields = (
            'job_number', 'created_by', 'created_at', 'updated_at',
            'balance', 'profit', 'vendor_balance', 'accepted_by', 'accepted_at', 'work_started_at', 'delivery_status',
            'branch',
        )

    def validate(self, attrs):
        request = self.context.get('request')
        if request and not request.user.is_superuser and self.ADMIN_FIELDS.intersection(self.initial_data):
            raise serializers.ValidationError('Finance and supplier payment fields require admin access.')
        if attrs.get('supplier'):
            attrs['vendor'] = attrs['supplier'].name
        elif self.instance and 'vendor' in attrs and attrs['vendor'] != self.instance.vendor and 'supplier' not in attrs:
            attrs['supplier'] = None
        for field in ('contact_number', 'description', 'transport_details', 'remarks', 'invoice_no'):
            if attrs.get(field) == '':
                attrs[field] = None
        customer = attrs.get('customer')
        if self.instance is None and not (attrs.get('customer_name') or customer):
            raise serializers.ValidationError({'customer_name': 'Enter a customer name or select an existing customer.'})
        if customer:
            if not attrs.get('customer_name'):
                attrs['customer_name'] = customer.name
            if not attrs.get('contact_number'):
                attrs['contact_number'] = customer.mobile or None
        if attrs.get('advance', 0) > attrs.get('total_amount', self.instance.total_amount if self.instance else 0):
            raise serializers.ValidationError({'advance': 'Advance cannot exceed total amount.'})
        if attrs.get('vendor_advance', 0) > attrs.get('vendor_total_payment', self.instance.vendor_total_payment if self.instance else 0):
            raise serializers.ValidationError({'vendor_advance': 'Supplier advance cannot exceed total supplier payment.'})
        if attrs.get('status') == OutJob.Status.IN_PROGRESS and not (self.instance and self.instance.status == OutJob.Status.IN_PROGRESS):
            raise serializers.ValidationError({'status': 'Accept and start this job from the job board first.'})
        new_status = attrs.get('status', self.instance.status if self.instance else OutJob.Status.PENDING)
        if self.instance and new_status == OutJob.Status.CANCELLED and self.instance.status == OutJob.Status.IN_PROGRESS and (
            self.instance.payment_status == 'paid' or self.instance.vendor_payment_status == 'paid'
        ):
            raise serializers.ValidationError({'status': 'An in-progress Out Job with completed customer or vendor payment cannot be cancelled.'})
        if new_status == OutJob.Status.COMPLETED and not (self.instance and self.instance.work_started_at):
            raise serializers.ValidationError({'status': 'Start work before completing this job.'})
        if self.instance and self.instance.status == OutJob.Status.COMPLETED and new_status != OutJob.Status.COMPLETED:
            raise serializers.ValidationError({'status': 'A completed job has already moved to delivery and cannot be reopened.'})
        return validate_job_finance(attrs, self.instance, vendor=True)

    @transaction.atomic
    def create(self, validated_data):
        from .services import initialize_job_finance, post_opening_advances
        cust_method = validated_data.pop('customer_payment_method', validated_data.pop('payment_method', 'Petty Cash'))
        cust_account = validated_data.pop('customer_cash_account', validated_data.pop('cash_account', None))
        vendor_method = validated_data.pop('vendor_payment_method', 'Petty Cash')
        vendor_account = validated_data.pop('vendor_cash_account', None)
        advances = initialize_job_finance(validated_data, vendor=True)
        job = super().create(validated_data)
        post_opening_advances(
            job, job.created_by, advances,
            cash_account=cust_account, method=cust_method,
            vendor_cash_account=vendor_account, vendor_method=vendor_method
        )
        return job

    @transaction.atomic
    def update(self, instance, validated_data):
        validated_data.pop('customer_payment_method', None)
        validated_data.pop('customer_cash_account', None)
        validated_data.pop('vendor_payment_method', None)
        validated_data.pop('vendor_cash_account', None)
        validated_data.pop('payment_method', None)
        validated_data.pop('cash_account', None)
        return super().update(instance, validated_data)


class InJobOfferSerializer(serializers.ModelSerializer):
    priority_label = serializers.SerializerMethodField()

    def get_priority_label(self, job):
        return job.priority_option.label if job.priority_option_id else job.get_priority_display()

    class Meta:
        model = InJob
        fields = ('id', 'job_number', 'job_type', 'priority', 'priority_label', 'printing_status')


class OutJobOfferSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutJob
        fields = ('id', 'job_number', 'job_type', 'priority', 'status')


class JobDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobDocument
        fields = (
            'id', 'pipeline_job', 'in_job', 'out_job', 'kind', 'file',
            'original_name', 'uploaded_by', 'created_at', 'updated_at',
        )
        read_only_fields = ('original_name', 'uploaded_by', 'created_at', 'updated_at')

    def validate(self, attrs):
        targets = [attrs.get('pipeline_job'), attrs.get('in_job'), attrs.get('out_job')]
        if self.instance:
            targets = [
                attrs.get('pipeline_job', self.instance.pipeline_job),
                attrs.get('in_job', self.instance.in_job),
                attrs.get('out_job', self.instance.out_job),
            ]
        if sum(target is not None for target in targets) != 1:
            raise serializers.ValidationError('Select exactly one pipeline, in, or out job.')
        request = self.context.get('request')
        if request and targets[0] and not user_has_module_access(request.user, 'pipeline'):
            raise serializers.ValidationError('Pipeline permission is required to attach a pipeline document.')
        if request:
            for job, module in zip(targets[1:], ('injobs', 'outjobs')):
                if job and not user_has_module_access(request.user, module):
                    raise serializers.ValidationError('Job module permission is required to attach a document.')
                if job and not request.user.is_superuser and job.accepted_by_id != request.user.pk:
                    raise serializers.ValidationError('Only the person who accepted this job may access its documents.')
        return attrs


class PipelineToInJobSerializer(serializers.Serializer):
    job_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    job_initials = serializers.CharField(max_length=30, required=False, allow_blank=True)
    reference_type = serializers.ChoiceField(choices=InJob.ReferenceType.choices, required=False)
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.active.all(), required=False, allow_null=True)
    customer_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    contact_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=InJob._meta.get_field('priority').choices, required=False)
    priority_option = serializers.PrimaryKeyRelatedField(queryset=InJobDropdownOption.objects.filter(is_active=True), required=False, allow_null=True)
    job_date = serializers.DateField(required=False)
    job_type = serializers.CharField(max_length=150, required=False, allow_blank=True)
    file_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    assigned_users = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.filter(is_active=True), many=True, required=False)
    everyone_in_department = serializers.PrimaryKeyRelatedField(queryset=Department.active.all(), required=False, allow_null=True)
    stock_item = serializers.PrimaryKeyRelatedField(queryset=StockItem.active.all(), required=False, allow_null=True)
    paper_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    gsm = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    paper_size = serializers.CharField(max_length=100, required=False, allow_blank=True)
    colour_spec = serializers.CharField(max_length=100, required=False, allow_blank=True)
    quantity = serializers.IntegerField(min_value=0, required=False)
    side_mode = serializers.ChoiceField(choices=('SS', 'DS'), required=False, allow_blank=True)
    side_option = serializers.PrimaryKeyRelatedField(queryset=InJobDropdownOption.objects.filter(is_active=True), required=False, allow_null=True)
    sheet_count = serializers.IntegerField(min_value=0, required=False)
    wastage_count = serializers.IntegerField(min_value=0, required=False)
    morning_count = serializers.IntegerField(min_value=0, required=False)
    counter_click_count = serializers.IntegerField(min_value=0, required=False)
    printer = serializers.PrimaryKeyRelatedField(queryset=Machine.active.all(), required=False, allow_null=True)
    designer = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.filter(is_active=True), required=False, allow_null=True)
    machine = serializers.PrimaryKeyRelatedField(queryset=Machine.active.all(), required=False, allow_null=True)
    lamination_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    regular_finish = serializers.BooleanField(required=False)
    corner_finish = serializers.BooleanField(required=False)
    binding_method = serializers.CharField(max_length=100, required=False, allow_blank=True)
    delivery_lp_office = serializers.BooleanField(required=False)
    delivery_porter = serializers.BooleanField(required=False)
    delivery_courier = serializers.BooleanField(required=False)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    advance = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    expenses = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    payment_status = serializers.ChoiceField(choices=PaymentStatus.choices, required=False)
    payment_option = serializers.PrimaryKeyRelatedField(queryset=InJobDropdownOption.objects.filter(is_active=True), required=False, allow_null=True)
    invoice_no = serializers.CharField(max_length=100, required=False, allow_blank=True)
    gst_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0'), max_value=Decimal('100'), required=False)
    remarks = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        apply_in_job_option_aliases(attrs)
        if attrs.get('advance', 0) > attrs.get('total_amount', 0):
            raise serializers.ValidationError({'advance': 'Advance cannot exceed the total amount.'})
        return attrs


class PipelineToOutJobSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.filter(is_active=True), required=False, allow_null=True)
    vendor = serializers.CharField(max_length=200)
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.active.all(), required=False, allow_null=True)
    customer_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    contact_number = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    job_type = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    quantity = serializers.IntegerField(min_value=1, required=False)
    priority = serializers.ChoiceField(choices=JobPriority.choices, required=False)
    delivery_date = serializers.DateField(required=False, allow_null=True)
    delivery_lp_office = serializers.BooleanField(required=False)
    delivery_porter = serializers.BooleanField(required=False)
    delivery_courier = serializers.BooleanField(required=False)
    remarks = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    advance = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    supplier_expenses = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    expenses = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    payment_status = serializers.ChoiceField(choices=PaymentStatus.choices, required=False)
    invoice_no = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    gst_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0'), required=False)
    vendor_total_payment = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    vendor_advance = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), required=False)
    vendor_payment_status = serializers.ChoiceField(choices=PaymentStatus.choices, required=False)
    assigned_users = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.filter(is_active=True), many=True, required=False)
    assigned_departments = serializers.PrimaryKeyRelatedField(queryset=Department.active.all(), many=True, required=False)

    def validate(self, attrs):
        request = self.context.get('request')
        if request and not request.user.is_superuser and OutJobSerializer.ADMIN_FIELDS.intersection(self.initial_data):
            raise serializers.ValidationError('Finance and supplier payment fields require admin access.')
        if attrs.get('supplier'):
            attrs['vendor'] = attrs['supplier'].name
        for field in ('contact_number', 'description', 'remarks', 'invoice_no'):
            if attrs.get(field) == '':
                attrs[field] = None
        if attrs.get('advance', 0) > attrs.get('total_amount', 0):
            raise serializers.ValidationError({'advance': 'Advance cannot exceed total amount.'})
        if attrs.get('vendor_advance', 0) > attrs.get('vendor_total_payment', 0):
            raise serializers.ValidationError({'vendor_advance': 'Supplier advance cannot exceed total supplier payment.'})
        return attrs


class DeliverySerializer(serializers.ModelSerializer):
    job_number = serializers.SerializerMethodField()
    job_type = serializers.SerializerMethodField()
    invoice_id = serializers.SerializerMethodField()
    invoice_no = serializers.SerializerMethodField()

    def get_invoice_id(self, delivery):
        job = delivery.in_job or delivery.out_job
        if not job:
            return None
        try:
            inv = getattr(job, 'invoice', None)
            return inv.id if inv else None
        except Exception:
            return None

    def get_invoice_no(self, delivery):
        job = delivery.in_job or delivery.out_job
        if not job:
            return None
        try:
            inv = getattr(job, 'invoice', None)
            return inv.invoice_no if inv else None
        except Exception:
            return None

    class Meta:
        model = Delivery
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at', 'branch')

    def validate(self, attrs):
        in_job = attrs.get('in_job', getattr(self.instance, 'in_job', None))
        out_job = attrs.get('out_job', getattr(self.instance, 'out_job', None))
        if sum(value is not None for value in (in_job, out_job)) != 1:
            raise serializers.ValidationError('Select exactly one in or out job.')
        job = in_job or out_job
        delivery_status = attrs.get('status', getattr(self.instance, 'status', Delivery.Status.PENDING))
        if delivery_status in {Delivery.Status.READY, Delivery.Status.DISPATCHED, Delivery.Status.DELIVERED}:
            complete = (
                job.printing_status == InJob.ProductionStatus.COMPLETED
                and job.finishing_status == InJob.ProductionStatus.COMPLETED
                if isinstance(job, InJob) else job.status == OutJob.Status.COMPLETED
            )
            paid = job.total_amount == 0 or job.advance >= job.total_amount
            if not complete:
                raise serializers.ValidationError({'status': 'Production must be complete before releasing a delivery.'})
            if not paid:
                raise serializers.ValidationError({'status': 'Full customer payment is required before releasing a delivery.'})
        return attrs

    def get_job_number(self, obj):
        return obj.job.job_number

    def get_job_type(self, obj):
        return 'in' if obj.in_job_id else 'out'


class StockMovementSerializer(serializers.ModelSerializer):
    stock_item_name = serializers.CharField(source='stock_item.name', read_only=True)

    class Meta:
        model = StockMovement
        fields = '__all__'
        read_only_fields = ('branch',)


class StockAdjustmentSerializer(serializers.Serializer):
    movement_type = serializers.ChoiceField(choices=StockMovement.MovementType.choices)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    reason = serializers.CharField(max_length=255)
    in_job = serializers.PrimaryKeyRelatedField(queryset=InJob.objects.all(), required=False, allow_null=True)
    out_job = serializers.PrimaryKeyRelatedField(queryset=OutJob.objects.all(), required=False, allow_null=True)

    def validate(self, attrs):
        if attrs.get('in_job') and attrs.get('out_job'):
            raise serializers.ValidationError('Select at most one in or out job.')
        return attrs


class MachineCounterSerializer(serializers.ModelSerializer):
    actual_clicks = serializers.IntegerField(read_only=True)
    difference = serializers.IntegerField(read_only=True)
    job_clicks_booked = serializers.IntegerField(source='calculated_job_clicks_booked', read_only=True)
    machine_name = serializers.CharField(source='machine.name', read_only=True)
    operator_display = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = MachineCounter
        fields = '__all__'
        read_only_fields = ('operator', 'branch', 'created_at', 'updated_at', 'actual_clicks', 'job_clicks_booked', 'difference')

    def validate(self, attrs):
        morning = attrs.get('morning_count', getattr(self.instance, 'morning_count', 0))
        ending = attrs.get('ending_count', getattr(self.instance, 'ending_count', 0))
        if ending < morning:
            raise serializers.ValidationError({'ending_count': 'Ending count cannot be lower than morning count.'})
        machine = attrs.get('machine', getattr(self.instance, 'machine', None))
        count_date = attrs.get('count_date', getattr(self.instance, 'count_date', None))
        if machine and count_date:
            existing = MachineCounter.objects.filter(machine=machine, count_date=count_date)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({'count_date': 'A counter record already exists for this machine and date. Edit that record instead.'})
        return attrs


class MachineStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MachineStatusHistory
        fields = '__all__'


class MachineStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Machine.OperationalStatus.choices)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class WastageRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = WastageRecord
        fields = '__all__'
        read_only_fields = ('recorded_by', 'branch', 'created_at', 'updated_at')

    def validate(self, attrs):
        in_job = attrs.get('in_job', getattr(self.instance, 'in_job', None))
        out_job = attrs.get('out_job', getattr(self.instance, 'out_job', None))
        if in_job and out_job:
            raise serializers.ValidationError('Select at most one in or out job.')
        return attrs


def _amount_in_words(amount):
    """Convert a Decimal amount to Indian English words (e.g. \u20b9 1,23,456.78 Rupees)."""
    from decimal import Decimal
    units = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
             'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
             'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def words_below_1000(n):
        if n == 0:
            return ''
        elif n < 20:
            return units[n]
        elif n < 100:
            return tens[n // 10] + ((' ' + units[n % 10]) if n % 10 else '')
        else:
            return units[n // 100] + ' Hundred' + ((' and ' + words_below_1000(n % 100)) if n % 100 else '')

    def indian_number_words(n):
        if n == 0:
            return 'Zero'
        parts = []
        crore = n // 10_000_000
        if crore:
            parts.append(words_below_1000(crore) + ' Crore')
            n %= 10_000_000
        lakh = n // 100_000
        if lakh:
            parts.append(words_below_1000(lakh) + ' Lakh')
            n %= 100_000
        thousand = n // 1000
        if thousand:
            parts.append(words_below_1000(thousand) + ' Thousand')
            n %= 1000
        if n:
            parts.append(words_below_1000(n))
        return ' '.join(parts)

    amount = Decimal(str(amount))
    rupees = int(amount)
    paise = round((amount - rupees) * 100)
    result = indian_number_words(rupees) + ' Rupees'
    if paise:
        result += ' and ' + indian_number_words(paise) + ' Paise'
    return result + ' Only'


class InvoiceSerializer(serializers.ModelSerializer):
    gst_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    cgst_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    sgst_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    taxable_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    grand_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    is_igst_applicable = serializers.BooleanField(read_only=True)
    amount_in_words = serializers.SerializerMethodField()
    job_number = serializers.SerializerMethodField()
    job_type = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    delivery_status = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = (
            'created_by', 'created_at', 'updated_at', 'gst_amount', 'cgst_amount',
            'sgst_amount', 'taxable_amount', 'grand_total', 'is_igst_applicable', 'amount_in_words',
            'branch',
        )

    def get_amount_in_words(self, obj):
        return obj.amount_in_words

    def get_job_number(self, obj):
        return obj.job.job_number if obj.job else ''

    def get_job_type(self, obj):
        return 'in' if obj.in_job_id else 'out'

    def get_customer_name(self, obj):
        return obj.customer_name_snapshot or (obj.job.customer_name if obj.job else '')

    def get_delivery_status(self, obj):
        job = obj.job
        if job and hasattr(job, 'delivery') and job.delivery:
            return job.delivery.status
        return 'delivered'

    def validate(self, attrs):
        in_job = attrs.get('in_job', getattr(self.instance, 'in_job', None))
        out_job = attrs.get('out_job', getattr(self.instance, 'out_job', None))
        if sum(value is not None for value in (in_job, out_job)) != 1:
            raise serializers.ValidationError('Select exactly one in or out job.')
        gst_percent = attrs.get('gst_percent', getattr(self.instance, 'gst_percent', 0))
        if not (0 <= float(gst_percent) <= 100):
            raise serializers.ValidationError({'gst_percent': 'GST percent must be between 0 and 100.'})
        discount = attrs.get('discount', getattr(self.instance, 'discount', 0))
        subtotal = attrs.get('subtotal', getattr(self.instance, 'subtotal', 0))
        if float(discount) > float(subtotal):
            raise serializers.ValidationError({'discount': 'Discount cannot exceed subtotal.'})
        return attrs

    INVOICE_FINANCE_FIELDS = frozenset((
        'subtotal', 'discount', 'taxable_amount', 'gst_percent', 'gst_amount',
        'cgst_amount', 'sgst_amount', 'grand_total', 'amount_in_words',
    ))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request and not request.user.is_superuser:
            profile = getattr(request.user, 'libin_profile', None)
            if profile and not profile.show_payment_details:
                for field in self.INVOICE_FINANCE_FIELDS:
                    data.pop(field, None)
        return data


class CompanySettingsSerializer(serializers.ModelSerializer):
    company_logo_url = serializers.SerializerMethodField()
    digital_signature_url = serializers.SerializerMethodField()

    class Meta:
        model = CompanySettings
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

    def get_company_logo_url(self, obj):
        request = self.context.get('request')
        if obj.company_logo:
            url = obj.company_logo.url
            return request.build_absolute_uri(url) if request else url
        return ''

    def get_digital_signature_url(self, obj):
        request = self.context.get('request')
        if obj.digital_signature:
            url = obj.digital_signature.url
            return request.build_absolute_uri(url) if request else url
        return ''

    def validate_gstin(self, value):
        value = value.strip().upper()
        if value and len(value) != 15:
            raise serializers.ValidationError('GSTIN must be exactly 15 characters.')
        return value

    def validate(self, attrs):
        # Singleton: allow only 1 instance; on create check there is none yet
        if self.instance is None and CompanySettings.objects.exists():
            raise serializers.ValidationError(
                'Company settings already exist. Use PATCH to update them.'
            )
        return attrs


class CashAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashAccount
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

    def validate(self, attrs):
        if self.instance and 'balance' in attrs and attrs['balance'] != self.instance.balance:
            raise serializers.ValidationError({'balance': 'Use payment or transfer endpoints to change the balance.'})
        return attrs


class CustomerPaymentSerializer(serializers.ModelSerializer):
    job_number = serializers.SerializerMethodField()
    delivery_status = serializers.SerializerMethodField()
    customer_name = serializers.CharField(source='job.customer_name', read_only=True)
    invoice_no = serializers.SerializerMethodField()
    cash_account_name = serializers.CharField(source='cash_account.name', read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.username', read_only=True)

    class Meta:
        model = CustomerPayment
        fields = '__all__'
        read_only_fields = ('id', 'in_job', 'out_job', 'branch', 'recorded_by', 'created_at', 'updated_at')

    def get_job_number(self, obj):
        return obj.job.job_number

    def get_delivery_status(self, obj):
        delivery = getattr(obj.job, 'delivery', None)
        return delivery.status if delivery else None

    def get_invoice_no(self, obj):
        job = obj.job
        invoice = getattr(job, 'invoice', None)
        return invoice.invoice_no if invoice else job.invoice_no or None


class CustomerPaymentCreateSerializer(serializers.Serializer):
    job_type = serializers.ChoiceField(choices=('in', 'out'))
    job_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    payment_type = serializers.ChoiceField(choices=CustomerPayment.PaymentType.choices, default=CustomerPayment.PaymentType.PAYMENT)
    payment_date = serializers.DateField()
    method = serializers.CharField(max_length=100, required=False, allow_blank=True)
    reference_no = serializers.CharField(max_length=150, required=False, allow_blank=True)
    cash_account = serializers.PrimaryKeyRelatedField(queryset=CashAccount.objects.filter(is_active=True), required=False, allow_null=True)


class VendorPaymentSerializer(serializers.ModelSerializer):
    job_number = serializers.CharField(source='out_job.job_number', read_only=True)
    supplier_name = serializers.SerializerMethodField()
    customer_name = serializers.CharField(source='out_job.customer_name', read_only=True)
    cash_account_name = serializers.CharField(source='cash_account.name', read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.username', read_only=True)

    def get_supplier_name(self, obj):
        return obj.out_job.supplier.name if obj.out_job.supplier_id else obj.out_job.vendor

    class Meta:
        model = VendorPayment
        fields = '__all__'
        read_only_fields = ('id', 'out_job', 'branch', 'recorded_by', 'created_at', 'updated_at')


class VendorPaymentCreateSerializer(serializers.Serializer):
    out_job = serializers.PrimaryKeyRelatedField(queryset=OutJob.objects.all())
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    payment_date = serializers.DateField()
    method = serializers.CharField(max_length=100, required=False, allow_blank=True)
    reference_no = serializers.CharField(max_length=150, required=False, allow_blank=True)
    cash_account = serializers.PrimaryKeyRelatedField(queryset=CashAccount.objects.filter(is_active=True), required=False, allow_null=True)


class CashTransactionSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source='account.name', read_only=True)
    source_reference = serializers.SerializerMethodField()

    def get_source_reference(self, obj):
        request = self.context.get('request')
        can_open_finance = bool(request and user_has_module_access(request.user, 'finance'))
        if obj.customer_payment_id:
            job = obj.customer_payment.job
            return {'label': f'Receipt · {job.job_number}', 'url': f'/customer-payments?job={job.pk}' if can_open_finance else None}
        if obj.vendor_payment_id:
            job = obj.vendor_payment.out_job
            return {'label': f'Supplier payment · {job.job_number}', 'url': f'/vendor-payments?job={job.pk}' if can_open_finance else None}
        if obj.cash_transfer_id:
            return {'label': f'Transfer · {obj.cash_transfer.reason}', 'url': '/cash-transfers'}
        entry = getattr(obj, 'financeentry', None)
        if entry:
            return {'label': f'{entry.category or entry.entry_type.title()} · {entry.description}', 'url': f'/finance?search={entry.description}' if can_open_finance else None}
        return {'label': obj.description, 'url': None}

    class Meta:
        model = CashTransaction
        fields = '__all__'


class CashTransferSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    destination_name = serializers.CharField(source='destination.name', read_only=True)
    movements = serializers.SerializerMethodField()

    def get_movements(self, obj):
        return list(obj.transactions.order_by('account_id').values('id', 'account__name', 'transaction_type', 'balance_after'))

    class Meta:
        model = CashTransfer
        fields = '__all__'


class CashTransferCreateSerializer(serializers.Serializer):
    source = serializers.PrimaryKeyRelatedField(queryset=CashAccount.objects.filter(is_active=True))
    destination = serializers.PrimaryKeyRelatedField(queryset=CashAccount.objects.filter(is_active=True))
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    transfer_date = serializers.DateField()
    reason = serializers.CharField(max_length=255)


class RoleSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        if self.instance and 'default_permissions' not in attrs:
            self.validate_default_permissions(self.instance.default_permissions)
        return attrs

    def validate_default_permissions(self, value):
        modules = dict(ModulePermissionOverride.MODULES)
        if not isinstance(value, dict) or any(key not in modules or type(allowed) is not bool for key, allowed in value.items()):
            raise serializers.ValidationError('Use known module names and boolean permission values.')
        request = self.context.get('request')
        if request:
            for module, allowed in value.items():
                check_permission_grant(request.user, module, allowed)
        return value

    class Meta:
        model = Role
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True)

    def validate(self, attrs):
        request = self.context.get('request')
        if self.instance and 'user' in attrs and attrs['user'].pk != self.instance.user_id:
            raise serializers.ValidationError({'user': 'A profile cannot be moved to another account.'})
        if request:
            target = attrs.get('user', self.instance.user if self.instance else None)
            if target:
                check_user_management(request.user, target)
            role = attrs.get('role', self.instance.role if self.instance else None)
            if role:
                for module, allowed in role.default_permissions.items():
                    check_permission_grant(request.user, module, allowed)
            branch = attrs.get('branch', self.instance.branch if self.instance else None)
            actor_branch = getattr(getattr(request.user, 'libin_profile', None), 'branch_id', None)
            if branch and not request.user.is_superuser and branch.pk != actor_branch:
                raise serializers.ValidationError({'branch': 'You may only assign users within your own branch.'})
        return attrs

    class Meta:
        model = UserProfile
        fields = ('id', 'user', 'username', 'full_name', 'role', 'department', 'branch', 'is_active', 'show_payment_details', 'created_at', 'updated_at')
        read_only_fields = ('created_at', 'updated_at')


class UserAccountSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    role = serializers.PrimaryKeyRelatedField(queryset=Role.objects.filter(is_active=True), required=False, allow_null=True)
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.filter(is_active=True), required=False, allow_null=True)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True)
    profile_active = serializers.BooleanField(required=False, default=True)
    show_payment_details = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = get_user_model()
        fields = ('id', 'username', 'first_name', 'last_name', 'email', 'is_active', 'password', 'role', 'department', 'branch', 'profile_active', 'show_payment_details')

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'Password is required for a new user.'})
        request = self.context.get('request')
        if request:
            if self.instance:
                check_user_management(request.user, self.instance)
            profile = getattr(self.instance, 'libin_profile', None) if self.instance else None
            role = attrs.get('role', profile.role if profile else None)
            if role:
                for module, allowed in role.default_permissions.items():
                    check_permission_grant(request.user, module, allowed)
            branch = attrs.get('branch', profile.branch if profile else None)
            actor_branch = getattr(getattr(request.user, 'libin_profile', None), 'branch_id', None)
            if branch and not request.user.is_superuser and branch.pk != actor_branch:
                raise serializers.ValidationError({'branch': 'You may only assign users within your own branch.'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        role = validated_data.pop('role', None)
        department = validated_data.pop('department', None)
        branch = validated_data.pop('branch', None)
        profile_active = validated_data.pop('profile_active', True)
        show_payment_details = validated_data.pop('show_payment_details', True)
        password = validated_data.pop('password', None)
        if role is None:
            request = self.context.get('request')
            if request is None or request.user.is_superuser:
                role = Role.objects.filter(is_active=True).first()
        user = get_user_model().objects.create_user(password=password, **validated_data)
        UserProfile.objects.create(
            user=user,
            role=role,
            department=department,
            branch=branch,
            is_active=profile_active,
            show_payment_details=show_payment_details,
        )
        return user

    @transaction.atomic
    def update(self, instance, validated_data):
        role = validated_data.pop('role', _UNSET)
        department = validated_data.pop('department', _UNSET)
        branch = validated_data.pop('branch', _UNSET)
        profile_active = validated_data.pop('profile_active', _UNSET)
        show_payment_details = validated_data.pop('show_payment_details', _UNSET)
        password = validated_data.pop('password', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
            from rest_framework.authtoken.models import Token
            Token.objects.filter(user=instance).delete()
        instance.save()
        profile = getattr(instance, 'libin_profile', None)
        if profile is None:
            profile, _ = UserProfile.objects.get_or_create(user=instance)
        if role is not _UNSET:
            profile.role = role
        if department is not _UNSET:
            profile.department = department
        if branch is not _UNSET:
            profile.branch = branch
        if profile_active is not _UNSET:
            profile.is_active = profile_active
        if show_payment_details is not _UNSET:
            profile.show_payment_details = show_payment_details
        profile.save()
        instance.libin_profile = profile
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        profile = getattr(instance, 'libin_profile', None)
        data['role'] = profile.role_id if profile else None
        data['role_name'] = profile.role.name if profile and profile.role else None
        data['department'] = profile.department_id if profile else None
        data['department_name'] = profile.department.name if profile and profile.department else None
        data['branch'] = profile.branch_id if profile else None
        data['branch_name'] = profile.branch.name if profile and profile.branch else None
        data['profile_active'] = profile.is_active if profile else instance.is_active
        data['show_payment_details'] = profile.show_payment_details if profile else True
        return data


class ModulePermissionOverrideSerializer(serializers.ModelSerializer):
    effective_access = serializers.BooleanField(read_only=True)

    def validate(self, attrs):
        request = self.context.get('request')
        if self.instance and 'user' in attrs and attrs['user'].pk != self.instance.user_id:
            raise serializers.ValidationError({'user': 'An override cannot be moved to another account.'})
        if self.instance and 'module' in attrs and attrs['module'] != self.instance.module:
            raise serializers.ValidationError({'module': 'An override cannot be moved to another module.'})
        if request:
            target = attrs.get('user', self.instance.user if self.instance else None)
            if target:
                check_user_management(request.user, target)
            module = attrs.get('module', self.instance.module if self.instance else None)
            access = attrs.get('access', self.instance.access if self.instance else 'default')
            check_permission_grant(request.user, module, access == 'allow')
            if access == 'default' and target:
                profile = getattr(target, 'libin_profile', None)
                role = profile.role if profile else None
                check_permission_grant(request.user, module, bool(role and role.default_permissions.get(module)))
        return attrs

    class Meta:
        model = ModulePermissionOverride
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at', 'effective_access')


class FollowUpSerializer(serializers.ModelSerializer):
    converted_pipeline_jobs = serializers.SerializerMethodField()
    converted_quotations = serializers.SerializerMethodField()

    def get_converted_pipeline_jobs(self, enquiry):
        return list(enquiry.converted_pipeline_jobs.values('id', 'job_number'))

    def get_converted_quotations(self, enquiry):
        return [
            {'id': quotation.id, 'quotation_number': quotation.quotation_number}
            for quotation in enquiry.converted_quotations.all()
        ]

    class Meta:
        model = FollowUp
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at')


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = '__all__'
        read_only_fields = ('recipient', 'read_at', 'created_at', 'updated_at', 'is_read')


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get('request'),
            username=attrs['username'],
            password=attrs['password'],
        )
        if user is None:
            raise serializers.ValidationError({'detail': 'Invalid username or password.'})
        attrs['user'] = user
        return attrs
