from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.text import slugify


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class Branch(TimeStampedModel):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30, unique=True)
    address = models.TextField(blank=True)
    contact_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_branches')
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ('name', 'id')
        indexes = [models.Index(fields=('is_active', 'name'))]

    def __str__(self):
        return f'{self.name} ({self.code})'


class Department(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        ordering = ('name',)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'department'
            candidate = base
            suffix = 2
            while Department.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                candidate = f'{base}-{suffix}'
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CustomerType(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True, db_index=True)

    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class Customer(TimeStampedModel):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='customers', null=True, blank=True, db_index=True)
    name = models.CharField(max_length=200, db_index=True)
    mobile = models.CharField(max_length=20, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    gst_number = models.CharField(max_length=15, blank=True, db_index=True)
    address = models.TextField(blank=True)
    billing_address = models.TextField(blank=True)
    delivery_address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    customer_type = models.ForeignKey(
        CustomerType,
        on_delete=models.PROTECT,
        related_name='customers',
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)

    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        ordering = ('name', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=('gst_number',),
                condition=~Q(gst_number=''),
                name='unique_nonempty_customer_gst',
            ),
        ]

    def __str__(self):
        return self.name


class Machine(TimeStampedModel):
    class OperationalStatus(models.TextChoices):
        RUNNING = 'running', 'Running'
        STOPPED = 'stopped', 'Stopped'
        BREAKDOWN = 'breakdown', 'Breakdown'
        MAINTENANCE = 'maintenance', 'Maintenance'

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=150)
    location = models.CharField(max_length=200, blank=True)
    operational_status = models.CharField(
        max_length=20,
        choices=OperationalStatus.choices,
        default=OperationalStatus.RUNNING,
        db_index=True,
    )
    status_reason = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)

    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        ordering = ('name',)
        constraints = [
            models.UniqueConstraint(
                fields=('is_default',),
                condition=Q(is_default=True),
                name='single_default_machine',
            ),
        ]

    def clean(self):
        super().clean()
        if self.operational_status in {
            self.OperationalStatus.STOPPED,
            self.OperationalStatus.BREAKDOWN,
        } and not self.status_reason.strip():
            raise ValidationError({'status_reason': 'A reason is required when a machine is stopped or in breakdown.'})

    def __str__(self):
        return f'{self.code} - {self.name}'


class StockCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class StockItem(TimeStampedModel):
    class Category(models.TextChoices):
        PAPER = 'paper', 'Paper'
        TONER = 'toner', 'Toner'
        INK = 'ink', 'Ink'
        FINISHING = 'finishing', 'Finishing Material'
        PACKAGING = 'packaging', 'Packaging'
        OTHER = 'other', 'Other'

    name = models.CharField(max_length=200, db_index=True)
    category = models.CharField(max_length=100, default=Category.PAPER, db_index=True)
    color = models.CharField(max_length=100, blank=True)
    gsm = models.PositiveIntegerField(null=True, blank=True)
    size = models.CharField(max_length=100, blank=True)
    current_stock = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    min_stock = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit = models.CharField(max_length=30, default='sheets')
    is_active = models.BooleanField(default=True, db_index=True)

    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        ordering = ('name', 'color', 'gsm', 'size')
        constraints = [
            models.CheckConstraint(condition=Q(current_stock__gte=0), name='stock_current_nonnegative'),
            models.CheckConstraint(condition=Q(min_stock__gte=0), name='stock_min_nonnegative'),
            models.UniqueConstraint(
                fields=('name', 'category', 'color', 'gsm', 'size'),
                name='unique_stock_item_variant',
            ),
        ]

    @property
    def is_low_stock(self):
        return self.current_stock <= self.min_stock

    def __str__(self):
        attributes = ', '.join(str(value) for value in (self.color, self.gsm, self.size) if value)
        return f'{self.name} ({attributes})' if attributes else self.name


class JobPriority(models.TextChoices):
    LOW = 'low', 'Low'
    NORMAL = 'normal', 'Normal'
    HIGH = 'high', 'High'
    URGENT = 'urgent', 'Urgent'


class PaymentStatus(models.TextChoices):
    UNPAID = 'unpaid', 'Unpaid'
    PARTIAL = 'partial', 'Partially Paid'
    PAID = 'paid', 'Paid'


class InJobDropdownOption(TimeStampedModel):
    class Field(models.TextChoices):
        PRIORITY = 'priority', 'Priority'
        SIDE_MODE = 'side_mode', 'Side'
        PAYMENT_STATUS = 'payment_status', 'Payment Status'
        JOB_TYPE = 'job_type', 'Job Type'
        LAMINATION_TYPE = 'lamination_type', 'Lamination'
        BINDING_METHOD = 'binding_method', 'Binding'

    field_name = models.CharField(max_length=30, choices=Field.choices)
    label = models.CharField(max_length=100)
    base_value = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_in_job_options')

    class Meta:
        ordering = ('field_name', 'label')
        constraints = [models.UniqueConstraint(fields=('field_name', 'label'), name='unique_in_job_dropdown_label')]

    def __str__(self):
        return f'{self.get_field_name_display()}: {self.label}'


class NumberedJobModel(TimeStampedModel):
    number_prefix = 'JOB'
    job_number = models.CharField(max_length=30, unique=True, null=True, blank=True, editable=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        needs_number = not self.job_number
        super().save(*args, **kwargs)
        if needs_number:
            generated = f'{self.number_prefix}-{timezone.localdate().year}-{self.pk:06d}'
            type(self).objects.filter(pk=self.pk, job_number__isnull=True).update(job_number=generated)
            self.job_number = generated


class PipelineJob(NumberedJobModel):
    number_prefix = 'PL'

    class Status(models.TextChoices):
        NEW = 'new', 'New'
        PROGRESS = 'progress', 'Progress'
        DESIGNING = 'designing', 'Designing'
        QUOTED = 'quoted', 'Quoted'
        APPROVED = 'approved', 'Approved'
        ON_HOLD = 'on_hold', 'On Hold'
        CONVERTED_IN = 'converted_in', 'Converted to In Job'
        CONVERTED_OUT = 'converted_out', 'Converted to Out Job'
        CANCELLED = 'cancelled', 'Cancelled'

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='pipeline_jobs', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='pipeline_jobs', null=True, blank=True, db_index=True)
    source_enquiry = models.ForeignKey('libinjobs.FollowUp', on_delete=models.SET_NULL, related_name='converted_pipeline_jobs', null=True, blank=True)
    client_name = models.CharField(max_length=200)
    contact_number = models.CharField(max_length=20, blank=True)
    job_date = models.DateField(default=timezone.localdate, db_index=True)
    job_type = models.CharField(max_length=150)
    size = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    printing_method = models.CharField(max_length=100, blank=True)
    reference_image = models.ImageField(upload_to='pipeline_references/%Y/%m/', blank=True)
    quote = models.TextField(blank=True)
    priority = models.CharField(max_length=10, choices=JobPriority.choices, default=JobPriority.NORMAL, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    assigned_designer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='designed_pipeline_jobs',
        null=True,
        blank=True,
    )
    remarks = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_pipeline_jobs',
    )

    class Meta:
        ordering = ('-job_date', '-id')

    def __str__(self):
        return f'{self.job_number or "Pipeline"} - {self.client_name}'


class InJob(NumberedJobModel):
    class ReferenceType(models.TextChoices):
        REGULAR = 'regular', 'Regular'
        CORPORATE = 'corporate', 'Corporate'
        WALKIN = 'walkin', 'Walk-in'

    number_prefix = 'IN'

    class ProductionStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        ON_HOLD = 'on_hold', 'On Hold'
        CANCELLED = 'cancelled', 'Cancelled'

    pipeline_job = models.OneToOneField(PipelineJob, on_delete=models.SET_NULL, related_name='in_job', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='in_jobs', null=True, blank=True, db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='in_jobs', null=True, blank=True)
    customer_name = models.CharField(max_length=200)
    contact_number = models.CharField(max_length=20, blank=True)
    job_date = models.DateField(default=timezone.localdate, db_index=True)
    reference_type = models.CharField(max_length=20, choices=ReferenceType.choices, default=ReferenceType.REGULAR, db_index=True)
    job_name = models.CharField(max_length=255, blank=True)
    job_initials = models.CharField(max_length=30, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    job_type = models.CharField(max_length=150)
    priority = models.CharField(max_length=10, choices=JobPriority.choices, default=JobPriority.NORMAL, db_index=True)
    priority_option = models.ForeignKey(InJobDropdownOption, on_delete=models.SET_NULL, related_name='priority_jobs', null=True, blank=True)
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name='in_jobs', null=True, blank=True)
    paper_type = models.CharField(max_length=100, blank=True)
    gsm = models.PositiveIntegerField(null=True, blank=True)
    paper_size = models.CharField(max_length=100, blank=True)
    colour_spec = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    side_mode = models.CharField(max_length=30, blank=True)
    side_option = models.ForeignKey(InJobDropdownOption, on_delete=models.SET_NULL, related_name='side_jobs', null=True, blank=True)
    sheet_count = models.PositiveIntegerField(default=0)
    click_count = models.PositiveIntegerField(default=0)
    morning_count = models.PositiveBigIntegerField(default=0)
    counter_click_count = models.PositiveBigIntegerField(default=0)
    wastage_count = models.PositiveIntegerField(default=0)
    wastage_operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='wastage_in_jobs', null=True, blank=True)
    printer = models.ForeignKey(Machine, on_delete=models.SET_NULL, related_name='printed_jobs', null=True, blank=True)
    designer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='designed_in_jobs', null=True, blank=True)
    printing_operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='printing_in_jobs', null=True, blank=True)
    machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, related_name='in_jobs', null=True, blank=True)
    printing_status = models.CharField(max_length=20, choices=ProductionStatus.choices, default=ProductionStatus.PENDING, db_index=True)
    lamination_type = models.CharField(max_length=100, blank=True)
    regular_finish = models.BooleanField(default=False)
    corner_finish = models.BooleanField(default=False)
    binding_method = models.CharField(max_length=100, blank=True)
    finishing_status = models.CharField(max_length=20, choices=ProductionStatus.choices, default=ProductionStatus.PENDING, db_index=True)
    delivery_lp_office = models.BooleanField(default=False)
    delivery_porter = models.BooleanField(default=False)
    delivery_courier = models.BooleanField(default=False)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    advance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True)
    payment_option = models.ForeignKey(InJobDropdownOption, on_delete=models.SET_NULL, related_name='payment_jobs', null=True, blank=True)
    invoice_no = models.CharField(max_length=100, blank=True, db_index=True)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    remarks = models.TextField(blank=True)
    assigned_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='assigned_in_jobs', blank=True)
    assigned_departments = models.ManyToManyField(Department, related_name='assigned_in_jobs', blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='accepted_in_jobs', null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    work_started_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_in_jobs')

    class Meta:
        ordering = ('-job_date', '-id')
        constraints = [
            models.CheckConstraint(condition=Q(total_amount__gte=0), name='injob_total_nonnegative'),
            models.CheckConstraint(condition=Q(advance__gte=0), name='injob_advance_nonnegative'),
            models.CheckConstraint(condition=Q(expenses__gte=0), name='injob_expenses_nonnegative'),
        ]

    @property
    def balance(self):
        return self.total_amount - self.advance

    @property
    def profit(self):
        return self.total_amount - self.expenses

    @property
    def current_count(self):
        return self.morning_count + self.counter_click_count

    @staticmethod
    def calculate_click_count(sheet_count, side_mode):
        return int(sheet_count or 0) * (2 if str(side_mode or '').upper() == 'DS' else 1)

    def save(self, *args, **kwargs):
        needs_number = not self.job_number
        super().save(*args, **kwargs)
        if needs_number:
            reference_code = {
                self.ReferenceType.REGULAR: 'R',
                self.ReferenceType.CORPORATE: 'C',
                self.ReferenceType.WALKIN: 'W',
            }.get(self.reference_type, 'R')
            daily_sequence = type(self).objects.filter(
                reference_type=self.reference_type,
                job_date=self.job_date,
                job_number__startswith=f'LP({reference_code})-',
            ).count() + 1
            self.job_number = f'LP({reference_code})-{daily_sequence:04d}_{self.job_date:%d%m%Y}'
            type(self).objects.filter(pk=self.pk).update(job_number=self.job_number)

    def __str__(self):
        return f'{self.job_number or "In Job"} - {self.customer_name}'


class OutJob(NumberedJobModel):
    number_prefix = 'OUT'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent to Vendor'
        IN_PROGRESS = 'in_progress', 'In Progress'
        READY = 'ready', 'Ready'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    pipeline_job = models.OneToOneField(PipelineJob, on_delete=models.SET_NULL, related_name='out_job', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='out_jobs', null=True, blank=True, db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='out_jobs', null=True, blank=True)
    customer_name = models.CharField(max_length=200)
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    vendor = models.CharField(max_length=200)
    supplier = models.ForeignKey('Supplier', on_delete=models.PROTECT, null=True, blank=True, related_name='out_jobs')
    job_type = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)
    delivery_date = models.DateField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    priority = models.CharField(max_length=10, choices=JobPriority.choices, default=JobPriority.NORMAL, db_index=True)
    transport_details = models.CharField(max_length=255, blank=True, null=True)
    delivery_lp_office = models.BooleanField(default=False)
    delivery_porter = models.BooleanField(default=False)
    delivery_courier = models.BooleanField(default=False)
    remarks = models.TextField(blank=True, null=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    advance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    supplier_expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True)
    invoice_no = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    vendor_total_payment = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vendor_advance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vendor_payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True)
    assigned_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='assigned_out_jobs', blank=True)
    assigned_departments = models.ManyToManyField(Department, related_name='assigned_out_jobs', blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='accepted_out_jobs', null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    work_started_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_out_jobs')

    class Meta:
        ordering = ('-id',)
        constraints = [
            models.CheckConstraint(condition=Q(total_amount__gte=0), name='outjob_total_nonnegative'),
            models.CheckConstraint(condition=Q(advance__gte=0), name='outjob_advance_nonnegative'),
            models.CheckConstraint(condition=Q(supplier_expenses__gte=0), name='outjob_supplier_expenses_nonnegative'),
            models.CheckConstraint(condition=Q(expenses__gte=0), name='outjob_expenses_nonnegative'),
            models.CheckConstraint(condition=Q(vendor_total_payment__gte=0), name='outjob_vendor_total_nonnegative'),
            models.CheckConstraint(condition=Q(vendor_advance__gte=0), name='outjob_vendor_advance_nonnegative'),
        ]

    @property
    def balance(self):
        return self.total_amount - self.advance

    @property
    def profit(self):
        return self.total_amount - self.supplier_expenses - self.expenses

    @property
    def vendor_balance(self):
        return self.vendor_total_payment - self.vendor_advance

    def __str__(self):
        return f'{self.job_number or "Out Job"} - {self.customer_name}'


class JobDocument(TimeStampedModel):
    class Kind(models.TextChoices):
        REFERENCE = 'reference', 'Reference / Example Design'
        DESIGN = 'design', 'Design File'
        PROOF = 'proof', 'Proof'
        OTHER = 'other', 'Other'

    pipeline_job = models.ForeignKey(PipelineJob, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    in_job = models.ForeignKey(InJob, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    out_job = models.ForeignKey(OutJob, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    file = models.FileField(upload_to='job_documents/%Y/%m/')
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='uploaded_job_documents')

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(pipeline_job__isnull=False, in_job__isnull=True, out_job__isnull=True)
                    | Q(pipeline_job__isnull=True, in_job__isnull=False, out_job__isnull=True)
                    | Q(pipeline_job__isnull=True, in_job__isnull=True, out_job__isnull=False)
                ),
                name='document_has_exactly_one_job',
            ),
        ]

    def clean(self):
        super().clean()
        targets = [self.pipeline_job_id, self.in_job_id, self.out_job_id]
        if sum(target is not None for target in targets) != 1:
            raise ValidationError('A document must belong to exactly one pipeline, in, or out job.')

    def __str__(self):
        return self.original_name or self.file.name


class Delivery(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        READY = 'ready', 'Ready for Delivery'
        DISPATCHED = 'dispatched', 'Dispatched'
        DELIVERED = 'delivered', 'Delivered'
        FAILED = 'failed', 'Failed'

    in_job = models.OneToOneField(InJob, on_delete=models.CASCADE, related_name='delivery', null=True, blank=True)
    out_job = models.OneToOneField(OutJob, on_delete=models.CASCADE, related_name='delivery', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='deliveries', null=True, blank=True, db_index=True)
    delivery_date = models.DateField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=150, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    method = models.CharField(max_length=100, blank=True)
    transport_company = models.CharField(max_length=150, blank=True)
    delivery_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    instructions = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_deliveries')

    class Meta:
        ordering = ('-delivery_date', '-id')
        constraints = [
            models.CheckConstraint(
                condition=(Q(in_job__isnull=False, out_job__isnull=True) | Q(in_job__isnull=True, out_job__isnull=False)),
                name='delivery_has_exactly_one_job',
            ),
            models.CheckConstraint(condition=Q(delivery_charges__gte=0), name='delivery_charges_nonnegative'),
        ]

    @property
    def job(self):
        return self.in_job or self.out_job

    def clean(self):
        super().clean()
        if sum(value is not None for value in (self.in_job_id, self.out_job_id)) != 1:
            raise ValidationError('A delivery must belong to exactly one in or out job.')
        if self.status in {self.Status.READY, self.Status.DISPATCHED, self.Status.DELIVERED}:
            job = self.job
            complete = (
                job.printing_status == InJob.ProductionStatus.COMPLETED
                and job.finishing_status == InJob.ProductionStatus.COMPLETED
                if self.in_job_id else job.status == OutJob.Status.COMPLETED
            )
            if not complete:
                raise ValidationError({'status': 'Production must be complete before releasing a delivery.'})
            if job.total_amount > 0 and job.advance < job.total_amount:
                raise ValidationError({'status': 'Full customer payment is required before releasing a delivery.'})

    def __str__(self):
        return f'Delivery - {self.job}'


class StockMovement(TimeStampedModel):
    class MovementType(models.TextChoices):
        IN = 'in', 'Stock In'
        OUT = 'out', 'Stock Out'
        ADJUSTMENT = 'adjustment', 'Adjustment'
        WASTAGE = 'wastage', 'Wastage'

    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name='movements')
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='stock_movements', null=True, blank=True, db_index=True)
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.CharField(max_length=255)
    in_job = models.ForeignKey(InJob, on_delete=models.SET_NULL, related_name='stock_movements', null=True, blank=True)
    out_job = models.ForeignKey(OutJob, on_delete=models.SET_NULL, related_name='stock_movements', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='stock_movements')

    class Meta:
        ordering = ('-created_at', '-id')
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='stock_movement_quantity_positive'),
            models.CheckConstraint(condition=Q(balance_after__gte=0), name='stock_movement_balance_nonnegative'),
            models.CheckConstraint(
                condition=~Q(in_job__isnull=False, out_job__isnull=False),
                name='stock_movement_at_most_one_job',
            ),
        ]

    def __str__(self):
        return f'{self.stock_item} {self.movement_type} {self.quantity}'


class MachineCounter(TimeStampedModel):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='machine_counters', null=True, blank=True, db_index=True)
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name='counters')
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='machine_counters')
    count_date = models.DateField(default=timezone.localdate, db_index=True)
    morning_count = models.PositiveBigIntegerField(default=0)
    ending_count = models.PositiveBigIntegerField(default=0)
    job_clicks_booked = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering = ('-count_date', 'machine__name')
        constraints = [
            models.UniqueConstraint(fields=('machine', 'count_date'), name='unique_machine_counter_per_day'),
            models.CheckConstraint(condition=Q(ending_count__gte=models.F('morning_count')), name='machine_ending_gte_morning'),
        ]

    @property
    def actual_clicks(self):
        return self.ending_count - self.morning_count

    @property
    def calculated_job_clicks_booked(self):
        return InJob.objects.filter(machine_id=self.machine_id, job_date=self.count_date).aggregate(total=Sum('click_count'))['total'] or 0

    @property
    def difference(self):
        return self.actual_clicks - self.calculated_job_clicks_booked

    def clean(self):
        super().clean()
        if self.ending_count < self.morning_count:
            raise ValidationError({'ending_count': 'Ending count cannot be lower than morning count.'})

    def __str__(self):
        return f'{self.machine} - {self.count_date}'


class MachineStatusHistory(TimeStampedModel):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='status_history')
    previous_status = models.CharField(max_length=20, choices=Machine.OperationalStatus.choices)
    new_status = models.CharField(max_length=20, choices=Machine.OperationalStatus.choices)
    reason = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='machine_status_changes')

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.machine}: {self.previous_status} -> {self.new_status}'


class WastageRecord(TimeStampedModel):
    class WastageType(models.TextChoices):
        PAPER = 'paper', 'Paper / Sheets'
        PRINT = 'print', 'Print Error'
        FINISHING = 'finishing', 'Finishing'
        MACHINE = 'machine', 'Machine'
        OTHER = 'other', 'Other'

    wastage_type = models.CharField(max_length=20, choices=WastageType.choices, db_index=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='wastage_records', null=True, blank=True, db_index=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, related_name='wastage_records', null=True, blank=True)
    stock_item = models.ForeignKey(StockItem, on_delete=models.SET_NULL, related_name='wastage_records', null=True, blank=True)
    in_job = models.ForeignKey(InJob, on_delete=models.SET_NULL, related_name='wastage_records', null=True, blank=True)
    out_job = models.ForeignKey(OutJob, on_delete=models.SET_NULL, related_name='wastage_records', null=True, blank=True)
    wastage_date = models.DateField(default=timezone.localdate, db_index=True)
    reason = models.TextField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='wastage_records')

    class Meta:
        ordering = ('-wastage_date', '-id')
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='wastage_quantity_positive'),
            models.CheckConstraint(condition=~Q(in_job__isnull=False, out_job__isnull=False), name='wastage_at_most_one_job'),
        ]

    def __str__(self):
        return f'{self.get_wastage_type_display()} - {self.quantity}'


class Invoice(TimeStampedModel):
    in_job = models.OneToOneField(InJob, on_delete=models.CASCADE, related_name='invoice', null=True, blank=True)
    out_job = models.OneToOneField(OutJob, on_delete=models.CASCADE, related_name='invoice', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='invoices', null=True, blank=True, db_index=True)
    invoice_no = models.CharField(max_length=100, unique=True)
    invoice_date = models.DateField(default=timezone.localdate, db_index=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_invoices')
    # Payment status (synced from job, stored as snapshot after delivery)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True)
    # Company snapshot — preserved even if CompanySettings changes later
    company_name_snapshot = models.CharField(max_length=200, blank=True)
    company_address_snapshot = models.TextField(blank=True)
    company_gstin_snapshot = models.CharField(max_length=15, blank=True)
    company_contact_snapshot = models.CharField(max_length=30, blank=True)
    company_email_snapshot = models.EmailField(blank=True)
    company_logo_url = models.CharField(max_length=500, blank=True)
    signature_url = models.CharField(max_length=500, blank=True)
    authorized_person_snapshot = models.CharField(max_length=200, blank=True)
    authorized_designation_snapshot = models.CharField(max_length=200, blank=True)
    terms_snapshot = models.TextField(blank=True)
    # Customer snapshot
    customer_name_snapshot = models.CharField(max_length=200, blank=True)
    customer_address_snapshot = models.TextField(blank=True)
    customer_gstin_snapshot = models.CharField(max_length=15, blank=True)
    customer_contact_snapshot = models.CharField(max_length=30, blank=True)
    # Order reference
    order_reference = models.CharField(max_length=100, blank=True)
    # Discount
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ('-invoice_date', '-id')
        constraints = [
            models.CheckConstraint(
                condition=(Q(in_job__isnull=False, out_job__isnull=True) | Q(in_job__isnull=True, out_job__isnull=False)),
                name='invoice_has_exactly_one_job',
            ),
            models.CheckConstraint(condition=Q(subtotal__gte=0), name='invoice_subtotal_nonnegative'),
            models.CheckConstraint(condition=Q(gst_percent__gte=0), name='invoice_gst_nonnegative'),
            models.CheckConstraint(condition=Q(discount__gte=0), name='invoice_discount_nonnegative'),
        ]

    @property
    def taxable_amount(self):
        from decimal import Decimal
        subtotal = Decimal(str(self.subtotal or 0))
        discount = Decimal(str(self.discount or 0))
        return max(subtotal - discount, Decimal('0'))

    @property
    def gst_amount(self):
        from decimal import Decimal, ROUND_HALF_UP
        taxable = Decimal(str(self.taxable_amount))
        gst = Decimal(str(self.gst_percent or 0))
        return (taxable * gst / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def cgst_amount(self):
        from decimal import Decimal, ROUND_HALF_UP
        return (self.gst_amount / Decimal('2')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def sgst_amount(self):
        return self.gst_amount - self.cgst_amount

    @property
    def grand_total(self):
        return self.taxable_amount + self.gst_amount

    @property
    def is_igst_applicable(self):
        """IGST applies when company and customer are in different GST states."""
        company_state = self.company_gstin_snapshot[:2] if len(self.company_gstin_snapshot) == 15 else ''
        customer_state = self.customer_gstin_snapshot[:2] if len(self.customer_gstin_snapshot) == 15 else ''
        return bool(company_state and customer_state and company_state != customer_state)

    @property
    def amount_in_words(self):
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

        try:
            amount = Decimal(str(self.grand_total))
            rupees = int(amount)
            paise = round((amount - rupees) * 100)
            result = indian_number_words(rupees) + ' Rupees'
            if paise:
                result += ' and ' + indian_number_words(paise) + ' Paise'
            return result + ' Only'
        except Exception:
            return ''

    @property
    def job(self):
        return self.in_job or self.out_job

    def clean(self):
        super().clean()
        if sum(value is not None for value in (self.in_job_id, self.out_job_id)) != 1:
            raise ValidationError('An invoice must belong to exactly one in or out job.')

    def __str__(self):
        return self.invoice_no


class CashAccount(TimeStampedModel):
    class AccountType(models.TextChoices):
        NET_BANK = 'net_bank', 'Cash 1 - Net Bank Cash'
        PETTY = 'petty', 'Cash 2 - Petty Cash'
        FIRST_PAYMENT = 'first_payment', 'Cash 3 - First Payment Cash'

    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=20, choices=AccountType.choices, unique=True)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ('account_type',)
        constraints = [models.CheckConstraint(condition=Q(balance__gte=0), name='cash_account_balance_nonnegative')]

    def __str__(self):
        return self.name


class CustomerPayment(TimeStampedModel):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='customer_payments', null=True, blank=True, db_index=True)
    class PaymentType(models.TextChoices):
        ADVANCE = 'advance', 'Advance'
        PAYMENT = 'payment', 'Payment'
        BALANCE = 'balance', 'Balance Payment'

    in_job = models.ForeignKey(InJob, on_delete=models.PROTECT, related_name='payments', null=True, blank=True)
    out_job = models.ForeignKey(OutJob, on_delete=models.PROTECT, related_name='payments', null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices, default=PaymentType.PAYMENT)
    payment_date = models.DateField(default=timezone.localdate, db_index=True)
    method = models.CharField(max_length=100, blank=True)
    reference_no = models.CharField(max_length=150, blank=True)
    cash_account = models.ForeignKey(CashAccount, on_delete=models.PROTECT, related_name='customer_payments', null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recorded_customer_payments')

    class Meta:
        ordering = ('-payment_date', '-id')
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='customer_payment_amount_positive'),
            models.CheckConstraint(
                condition=(Q(in_job__isnull=False, out_job__isnull=True) | Q(in_job__isnull=True, out_job__isnull=False)),
                name='customer_payment_has_exactly_one_job',
            ),
        ]

    @property
    def job(self):
        return self.in_job or self.out_job

    def __str__(self):
        return f'{self.job} - {self.amount}'


class VendorPayment(TimeStampedModel):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='vendor_payments', null=True, blank=True, db_index=True)
    out_job = models.ForeignKey(OutJob, on_delete=models.PROTECT, related_name='vendor_payments')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField(default=timezone.localdate, db_index=True)
    method = models.CharField(max_length=100, blank=True)
    reference_no = models.CharField(max_length=150, blank=True)
    cash_account = models.ForeignKey(CashAccount, on_delete=models.PROTECT, related_name='vendor_payments', null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recorded_vendor_payments')

    class Meta:
        ordering = ('-payment_date', '-id')
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='vendor_payment_amount_positive')]

    def __str__(self):
        return f'{self.out_job} - {self.amount}'


class CashTransaction(TimeStampedModel):
    class TransactionType(models.TextChoices):
        CREDIT = 'credit', 'Credit'
        DEBIT = 'debit', 'Debit'
        TRANSFER_IN = 'transfer_in', 'Transfer In'
        TRANSFER_OUT = 'transfer_out', 'Transfer Out'

    account = models.ForeignKey(CashAccount, on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices, db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    transaction_date = models.DateField(default=timezone.localdate, db_index=True)
    description = models.CharField(max_length=255)
    remarks = models.TextField(blank=True)
    customer_payment = models.OneToOneField(CustomerPayment, on_delete=models.PROTECT, related_name='cash_transaction', null=True, blank=True)
    vendor_payment = models.OneToOneField(VendorPayment, on_delete=models.PROTECT, related_name='cash_transaction', null=True, blank=True)
    cash_transfer = models.ForeignKey('CashTransfer', on_delete=models.PROTECT, related_name='transactions', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='cash_transactions')

    class Meta:
        ordering = ('-transaction_date', '-id')
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='cash_transaction_amount_positive'),
            models.CheckConstraint(condition=Q(balance_after__gte=0), name='cash_transaction_balance_nonnegative'),
            models.CheckConstraint(
                condition=~Q(customer_payment__isnull=False, vendor_payment__isnull=False),
                name='cash_transaction_at_most_one_payment',
            ),
        ]

    def __str__(self):
        return f'{self.account} - {self.transaction_type} {self.amount}'


class CashTransfer(TimeStampedModel):
    source = models.ForeignKey(CashAccount, on_delete=models.PROTECT, related_name='outgoing_transfers')
    destination = models.ForeignKey(CashAccount, on_delete=models.PROTECT, related_name='incoming_transfers')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    transfer_date = models.DateField(default=timezone.localdate, db_index=True)
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='cash_transfers')

    class Meta:
        ordering = ('-transfer_date', '-id')
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='cash_transfer_amount_positive'),
            models.CheckConstraint(condition=~Q(source=models.F('destination')), name='cash_transfer_distinct_accounts'),
        ]

    def __str__(self):
        return f'{self.source} -> {self.destination}: {self.amount}'


class Role(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    default_permissions = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class UserProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='libin_profile')
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name='users', null=True, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, related_name='users', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='users', null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    show_payment_details = models.BooleanField(default=True)

    class Meta:
        ordering = ('user__first_name', 'user__username')

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class ModulePermissionOverride(TimeStampedModel):
    class Access(models.TextChoices):
        DEFAULT = 'default', 'Use Role Default'
        ALLOW = 'allow', 'Allow'
        DENY = 'deny', 'Deny'

    MODULES = (
        ('dashboard', 'Dashboard'), ('pipeline', 'Pipeline'), ('jobboard', 'Job Board'), ('injobs', 'In Jobs'),
        ('outjobs', 'Out Jobs'), ('delivery', 'Delivery'), ('stock', 'Stock'),
        ('customers', 'Customers'), ('machine', 'Machine'), ('cash', 'Cash'),
        ('wastage', 'Wastage'), ('finance', 'Finance'), ('accounts', 'Accounts'),
        ('reports', 'Reports'), ('notifications', 'Notifications'),
        ('followups', 'Enquiries'), ('suppliers', 'Suppliers'), ('quotations', 'Quotations'), ('users', 'Users'), ('permissions', 'Permissions'),
        ('company_settings', 'Company Settings'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='module_permission_overrides')
    module = models.CharField(max_length=30, choices=MODULES)
    access = models.CharField(max_length=10, choices=Access.choices, default=Access.DEFAULT)

    class Meta:
        ordering = ('user__username', 'module')
        constraints = [models.UniqueConstraint(fields=('user', 'module'), name='unique_user_module_override')]

    @property
    def effective_access(self):
        from .permissions import user_has_module_access
        return user_has_module_access(self.user, self.module)

    def __str__(self):
        return f'{self.user} - {self.module}: {self.access}'


class FollowUp(TimeStampedModel):
    contact_number = models.CharField(max_length=30, blank=True, null=True)
    follow_up_date = models.DateField(default=timezone.localdate, db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, related_name='follow_ups', null=True, blank=True)
    customer_name = models.CharField(max_length=200)
    job_type = models.CharField(max_length=150, blank=True)
    size = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    printing_method = models.CharField(max_length=100, blank=True)
    quote = models.TextField(blank=True)
    remarks = models.TextField(blank=True)
    is_completed = models.BooleanField(default=False, db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='assigned_follow_ups', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_follow_ups')

    class Meta:
        ordering = ('is_completed', 'follow_up_date', '-id')

    def __str__(self):
        return f'{self.customer_name} - {self.follow_up_date}'


class Quotation(TimeStampedModel):
    source_enquiry = models.ForeignKey('libinjobs.FollowUp', on_delete=models.SET_NULL, related_name='converted_quotations', null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='quotations', null=True, blank=True, db_index=True)
    customer_name = models.CharField(max_length=200)
    contact_number = models.CharField(max_length=30, null=True, blank=True)
    billing_address = models.TextField(null=True, blank=True)
    quotation_date = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='draft', choices=[(s, s.title()) for s in ('draft', 'sent', 'accepted', 'rejected', 'cancelled')])
    items = models.JSONField(default=list)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    notes = models.TextField(null=True, blank=True)
    terms = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ('-quotation_date', '-id')
        constraints = [
            models.CheckConstraint(condition=Q(discount__gte=0), name='quotation_discount_nonnegative'),
            models.CheckConstraint(condition=Q(gst_percent__gte=0, gst_percent__lte=100), name='quotation_gst_range'),
        ]

    @property
    def quotation_number(self):
        return f'QUO-{self.pk:06d}'

    @property
    def totals(self):
        from decimal import Decimal, ROUND_HALF_UP
        money = lambda value: value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        subtotal = sum((money(Decimal(item['quantity']) * Decimal(item['unit_price'])) for item in self.items), Decimal('0'))
        taxable = subtotal - self.discount
        tax = money(taxable * self.gst_percent / 100)
        return {'subtotal': subtotal, 'taxable_amount': taxable, 'gst_amount': tax, 'grand_total': taxable + tax}


class Supplier(TimeStampedModel):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=150, blank=True, null=True)
    mobile = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    gst_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    services = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name', 'id')

    def __str__(self):
        return self.name


class FinanceEntry(TimeStampedModel):
    entry_type = models.CharField(max_length=10, choices=(('credit', 'Credit'), ('debit', 'Debit'), ('expense', 'Expense')))
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    entry_date = models.DateField(default=timezone.localdate)
    account = models.ForeignKey(CashAccount, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    description = models.CharField(max_length=255)
    reference_no = models.CharField(max_length=100, blank=True, null=True)
    request_key = models.UUIDField(unique=True)
    cash_transaction = models.OneToOneField(CashTransaction, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ('-entry_date', '-id')
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='finance_entry_positive_amount')]


class Notification(TimeStampedModel):
    class Type(models.TextChoices):
        JOB = 'job', 'Job'
        STOCK = 'stock', 'Stock'
        DELIVERY = 'delivery', 'Delivery'
        PAYMENT = 'payment', 'Payment'
        SYSTEM = 'system', 'System'

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='libin_notifications')
    notification_type = models.CharField(max_length=20, choices=Type.choices, default=Type.SYSTEM, db_index=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    target_url = models.CharField(max_length=500, blank=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ('-created_at',)

    @property
    def is_read(self):
        return self.read_at is not None

    def mark_read(self):
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=('read_at', 'updated_at'))

    def __str__(self):
        return self.title


class CompanySettings(TimeStampedModel):
    """Singleton model for company-wide settings used in invoices and quotations."""
    company_name = models.CharField(max_length=200)
    company_logo = models.ImageField(upload_to='company/logos/', blank=True)
    address = models.TextField(blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    contact_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    digital_signature = models.ImageField(upload_to='company/signatures/', blank=True)
    authorized_person_name = models.CharField(max_length=200, blank=True)
    authorized_person_designation = models.CharField(max_length=200, blank=True)
    terms_and_conditions = models.TextField(blank=True)
    bank_name = models.CharField(max_length=200, blank=True)
    bank_account_number = models.CharField(max_length=50, blank=True)
    bank_ifsc = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ('id',)
        verbose_name = 'Company Settings'
        verbose_name_plural = 'Company Settings'

    def clean(self):
        super().clean()
        if self.gstin and len(self.gstin) != 15:
            raise ValidationError({'gstin': 'GSTIN must be exactly 15 characters.'})

    @classmethod
    def get_instance(cls):
        """Return the single settings record or None."""
        return cls.objects.first()

    def __str__(self):
        return self.company_name or 'Company Settings'
