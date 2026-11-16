import mimetypes

from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import FileResponse, Http404
from django.db.models import Count, F, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework import mixins
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Branch, CompanySettings, Supplier, FinanceEntry, Quotation,
    CashAccount, CashTransaction, CashTransfer, Customer, CustomerPayment,
    CustomerType, Delivery, Department, FollowUp, InJob, InJobDropdownOption, Invoice, JobDocument, Machine,
    MachineCounter, MachineStatusHistory, ModulePermissionOverride, Notification,
    OutJob, PipelineJob, Role, StockCategory, StockItem, StockMovement, UserProfile,
    VendorPayment, WastageRecord,
)
from .serializers import (
    BranchSerializer, CompanySettingsSerializer, SupplierSerializer, FinanceEntrySerializer, QuotationSerializer,
    CustomerSerializer,
    CustomerPaymentCreateSerializer,
    CustomerPaymentSerializer,
    CustomerTypeSerializer,
    CashAccountSerializer,
    CashTransactionSerializer,
    CashTransferCreateSerializer,
    CashTransferSerializer,
    DeliverySerializer,
    DepartmentSerializer,
    FollowUpSerializer,
    InJobSerializer,
    InJobDropdownOptionSerializer,
    InJobOfferSerializer,
    InvoiceSerializer,
    JobDocumentSerializer,
    MachineSerializer,
    MachineCounterSerializer,
    MachineStatusChangeSerializer,
    MachineStatusHistorySerializer,
    LoginSerializer,
    ModulePermissionOverrideSerializer,
    NotificationSerializer,
    OutJobSerializer,
    OutJobOfferSerializer,
    PipelineJobSerializer,
    PipelineToInJobSerializer,
    PipelineToOutJobSerializer,
    StockCategorySerializer,
    StockItemSerializer,
    StockAdjustmentSerializer,
    StockMovementSerializer,
    RoleSerializer,
    UserAccountSerializer,
    UserProfileSerializer,
    WastageRecordSerializer,
    VendorPaymentCreateSerializer,
    VendorPaymentSerializer,
)
from .permissions import user_has_module_access


def user_branch(user):
    profile = getattr(user, 'libin_profile', None)
    return getattr(profile, 'branch', None)


def branch_for_request(request):
    branch = user_branch(request.user)
    if branch and not branch.is_active:
        return None
    return branch


def save_with_branch(serializer, request, **kwargs):
    """Force branch ownership for non-superusers; never trust a submitted branch id."""
    if not request.user.is_superuser and hasattr(serializer.Meta.model, 'branch'):
        branch = branch_for_request(request)
        # Keep legacy unassigned accounts operational during migration. Once a
        # user has a branch, ownership is always forced server-side.
        if branch is not None:
            kwargs['branch'] = branch
    return serializer.save(**kwargs)


def scope_branch_queryset(queryset, user):
    """Apply server-side branch isolation to any model carrying branch ownership."""
    if 'branch' not in {field.name for field in queryset.model._meta.get_fields()}:
        return queryset
    if user.is_superuser:
        return queryset
    branch = user_branch(user)
    # Legacy users/records remain usable without being silently assigned to a branch;
    # they can see only the still-unassigned legacy records.
    return queryset.filter(branch=branch) if branch else queryset.filter(branch__isnull=True)


def authentication_payload(user, token=None):
    profile = getattr(user, 'libin_profile', None)
    payload = {
        'user': {
            'id': user.pk,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'is_superuser': user.is_superuser,
            'show_payment_details': user.is_superuser or (profile.show_payment_details if profile else True),
            'role': profile.role_id if profile else None,
            'role_name': profile.role.name if profile and profile.role else None,
            'department': profile.department_id if profile else None,
            'department_name': profile.department.name if profile and profile.department else None,
            'branch': profile.branch_id if profile else None,
            'branch_name': profile.branch.name if profile and profile.branch else None,
        },
        'permissions': {
            module: user_has_module_access(user, module)
            for module, _label in ModulePermissionOverride.MODULES
        },
    }
    if token is not None:
        payload['token'] = token.key
    return payload


class LoginAPIView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, _created = Token.objects.get_or_create(user=user)
        return Response(authentication_payload(user, token))


class LogoutAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobBoardAcceptedSummaryAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        if not request.user.is_superuser:
            return Response({'detail': 'Superadmin access is required.'}, status=status.HTTP_403_FORBIDDEN)

        employees = {}
        totals = {'employees': 0, 'accepted_jobs': 0, 'in_jobs': 0, 'out_jobs': 0}
        for kind, model, status_field in (
            ('in', InJob, 'printing_status'), ('out', OutJob, 'status'),
        ):
            for job in model.objects.filter(accepted_by__isnull=False).select_related('accepted_by').order_by('-accepted_at', '-id'):
                user = job.accepted_by
                employee = employees.setdefault(user.pk, {
                    'user_id': user.pk,
                    'employee': user.get_full_name() or user.username,
                    'username': user.username,
                    'accepted_count': 0,
                    'in_jobs': 0,
                    'out_jobs': 0,
                    'projects': [],
                })
                employee['accepted_count'] += 1
                employee[f'{kind}_jobs'] += 1
                totals['accepted_jobs'] += 1
                totals[f'{kind}_jobs'] += 1
                employee['projects'].append({
                    'id': job.pk,
                    'kind': kind,
                    'job_number': job.job_number,
                    'project_name': job.job_name if kind == 'in' and job.job_name else job.job_type,
                    'customer_name': job.customer_name,
                    'accepted_at': job.accepted_at,
                    'status': getattr(job, status_field),
                })
        totals['employees'] = len(employees)
        return Response({
            'totals': totals,
            'employees': sorted(employees.values(), key=lambda item: (-item['accepted_count'], item['employee'].casefold())),
        })


class CurrentUserAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(authentication_payload(request.user))
from .services import (
    adjust_stock, auto_generate_invoice, change_machine_status, convert_pipeline_to_in_job,
    convert_pipeline_to_out_job, record_customer_payment, record_vendor_payment,
    handoff_completed_job_to_delivery,
    transfer_cash,
)


class SearchableModelViewSet(viewsets.ModelViewSet):
    search_fields = ()

    def get_queryset(self):
        queryset = super().get_queryset()
        field_names = {field.name for field in queryset.model._meta.get_fields()}
        if 'branch' in field_names:
            if self.request.user.is_superuser:
                requested_branch = self.request.query_params.get('branch')
                if requested_branch:
                    queryset = queryset.filter(branch_id=requested_branch)
            else:
                branch = user_branch(self.request.user)
                queryset = queryset.filter(branch=branch) if branch else queryset.filter(branch__isnull=True)
        search = self.request.query_params.get('search', '').strip()
        if search and self.search_fields:
            query = Q()
            for field in self.search_fields:
                query |= Q(**{f'{field}__icontains': search})
            queryset = queryset.filter(query)

        active = self.request.query_params.get('is_active')
        if active is not None and hasattr(queryset.model, 'is_active'):
            queryset = queryset.filter(is_active=active.lower() in {'1', 'true', 'yes'})
        return queryset


class BranchViewSet(SearchableModelViewSet):
    queryset = Branch.objects.select_related('manager').prefetch_related('users')
    serializer_class = BranchSerializer
    search_fields = ('name', 'code', 'address', 'contact_number', 'email')

    def get_queryset(self):
        queryset = Branch.objects.select_related('manager').prefetch_related('users')
        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search) | Q(address__icontains=search) | Q(contact_number__icontains=search) | Q(email__icontains=search))
        active = self.request.query_params.get('is_active')
        if active is not None:
            queryset = queryset.filter(is_active=active.lower() in {'1', 'true', 'yes'})
        return queryset


class DepartmentViewSet(SearchableModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    search_fields = ('name', 'slug')


class InJobDropdownOptionViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = InJobDropdownOption.objects.filter(is_active=True)
    serializer_class = InJobDropdownOptionSerializer
    module_name = 'injobs'

    def get_queryset(self):
        queryset = super().get_queryset()
        field_name = self.request.query_params.get('field_name')
        return queryset.filter(field_name=field_name) if field_name else queryset

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, created_by=self.request.user)


class CustomerTypeViewSet(SearchableModelViewSet):
    queryset = CustomerType.objects.all()
    serializer_class = CustomerTypeSerializer
    search_fields = ('name',)


class CustomerViewSet(SearchableModelViewSet):
    queryset = Customer.objects.select_related('customer_type')
    serializer_class = CustomerSerializer
    search_fields = ('name', 'mobile', 'gst_number')

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request)

    def get_queryset(self):
        queryset = super().get_queryset()
        customer_type = self.request.query_params.get('customer_type')
        return queryset.filter(customer_type_id=customer_type) if customer_type else queryset


class MachineViewSet(SearchableModelViewSet):
    queryset = Machine.objects.all()
    serializer_class = MachineSerializer
    search_fields = ('code', 'name', 'location')

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.query_params.get('status')
        return queryset.filter(operational_status=status) if status else queryset

    @action(detail=True, methods=('post',), url_path='set-status')
    def set_status(self, request, pk=None):
        serializer = MachineStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            history = change_machine_status(
                self.get_object(), serializer.validated_data['status'],
                serializer.validated_data.get('reason', ''), request.user,
            )
        except DjangoValidationError as exc:
            detail = getattr(exc, 'message_dict', None) or {'detail': exc.messages}
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(MachineStatusHistorySerializer(history).data)


class StockCategoryViewSet(SearchableModelViewSet):
    queryset = StockCategory.objects.filter(is_active=True)
    serializer_class = StockCategorySerializer
    search_fields = ('name',)

    def list(self, request, *args, **kwargs):
        defaults = ['Paper', 'Toner', 'Ink', 'Finishing Material', 'Packaging', 'Other']
        for cat in defaults:
            StockCategory.objects.get_or_create(name=cat)
        for cat in StockItem.objects.values_list('category', flat=True).distinct():
            if cat:
                StockCategory.objects.get_or_create(name=cat)
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, created_by=self.request.user)


class StockItemViewSet(SearchableModelViewSet):
    queryset = StockItem.objects.all()
    serializer_class = StockItemSerializer
    search_fields = ('name', 'category', 'color', 'size', 'unit')

    def get_queryset(self):
        queryset = super().get_queryset()
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        if self.request.query_params.get('low_stock', '').lower() in {'1', 'true', 'yes'}:
            queryset = queryset.filter(current_stock__lte=F('min_stock'))
        return queryset

    @action(detail=True, methods=('post',), url_path='adjust')
    def adjust(self, request, pk=None):
        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data.copy()
        try:
            movement = adjust_stock(self.get_object(), user=request.user, **data)
        except DjangoValidationError as exc:
            detail = getattr(exc, 'message_dict', None) or {'detail': exc.messages}
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class PipelineJobViewSet(SearchableModelViewSet):
    queryset = PipelineJob.objects.select_related('customer', 'assigned_designer', 'created_by')
    serializer_class = PipelineJobSerializer
    search_fields = ('job_number', 'client_name', 'contact_number', 'job_type')

    @action(detail=False, methods=('get',), url_path='assignment-options')
    def assignment_options(self, request):
        return Response(list(get_user_model().objects.filter(is_active=True).values('id', 'username', 'first_name', 'last_name')))

    @action(detail=True, methods=('get',), url_path='in-job-options')
    def in_job_options(self, request, pk=None):
        self.get_object()
        users = [
            {'id': user.pk, 'username': user.username, 'first_name': user.first_name, 'last_name': user.last_name}
            for user in get_user_model().objects.filter(is_active=True).order_by('username')
            if user_has_module_access(user, 'injobs')
        ]
        job_types = sorted(set(PipelineJob.objects.exclude(job_type='').values_list('job_type', flat=True)) |
                           set(InJob.objects.exclude(job_type='').values_list('job_type', flat=True)) |
                           set(InJobDropdownOption.objects.filter(field_name='job_type', is_active=True).values_list('label', flat=True)))
        return Response({
            'customers': list(Customer.active.values('id', 'name', 'mobile')),
            'stock_items': list(StockItem.active.values('id', 'name', 'category', 'gsm', 'size', 'color')),
            'machines': list(Machine.active.values('id', 'name', 'is_default')),
            'users': users,
            'departments': list(Department.active.values('id', 'name')),
            'job_types': job_types,
            'lamination_types': sorted(set(InJob.objects.exclude(lamination_type='').values_list('lamination_type', flat=True)) |
                                       set(InJobDropdownOption.objects.filter(field_name='lamination_type', is_active=True).values_list('label', flat=True))),
            'binding_methods': sorted(set(InJob.objects.exclude(binding_method='').values_list('binding_method', flat=True)) |
                                      set(InJobDropdownOption.objects.filter(field_name='binding_method', is_active=True).values_list('label', flat=True))),
            'custom_options': {field: list(InJobDropdownOption.objects.filter(field_name=field, is_active=True).values('id', 'label', 'base_value'))
                               for field in ('priority', 'side_mode', 'payment_status')},
        })

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, created_by=self.request.user)

    @action(detail=True, methods=('get',), url_path='reference-image')
    def reference_image(self, request, pk=None):
        job = self.get_object()
        if not job.reference_image:
            raise Http404('No reference image is attached to this job.')
        try:
            image = job.reference_image.open('rb')
        except FileNotFoundError as exc:
            raise Http404('The reference image is unavailable.') from exc
        return FileResponse(image, content_type=mimetypes.guess_type(job.reference_image.name)[0] or 'application/octet-stream')

    def get_queryset(self):
        queryset = super().get_queryset()
        for parameter in ('status', 'priority'):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{parameter: value})
        return queryset

    @staticmethod
    def _validation_response(exc):
        detail = getattr(exc, 'message_dict', None) or {'detail': exc.messages}
        return Response(detail, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=('post',), url_path='convert-to-in-job')
    def convert_to_in_job(self, request, pk=None):
        serializer = PipelineToInJobSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job = convert_pipeline_to_in_job(self.get_object(), request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            return self._validation_response(exc)
        return Response(InJobOfferSerializer(job).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=('post',), url_path='convert-to-out-job')
    def convert_to_out_job(self, request, pk=None):
        serializer = PipelineToOutJobSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        try:
            job = convert_pipeline_to_out_job(self.get_object(), request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            return self._validation_response(exc)
        return Response(OutJobOfferSerializer(job).data, status=status.HTTP_201_CREATED)


class JobClaimMixin:
    offer_statuses = ()
    status_field = ''
    offer_serializer_class = None

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in {'update', 'partial_update'}:
            # Lock only the job row; nullable joined relations cannot be locked on PostgreSQL.
            queryset = queryset.select_related(None).select_for_update()
        if self.action in {'list', 'retrieve', 'update', 'partial_update', 'destroy', 'cancel'} and not self.request.user.is_superuser:
            return queryset.filter(accepted_by=self.request.user)
        return queryset

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(self.offer_serializer_class(serializer.instance).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        with transaction.atomic():
            job = serializer.save()
            handoff_completed_job_to_delivery(job, self.request.user)
            job.refresh_from_db()

    def check_permissions(self, request):
        super().check_permissions(request)
        if self.action in {'available', 'my_jobs', 'accept', 'start'} and not user_has_module_access(request.user, 'jobboard'):
            self.permission_denied(request, message='Job Board access is required.')

    def eligible_offers(self, request):
        queryset = self.get_queryset().filter(accepted_by__isnull=True, **{f'{self.status_field}__in': self.offer_statuses})
        if request.user.is_superuser:
            return queryset
        profile = getattr(request.user, 'libin_profile', None)
        eligible = Q(assigned_users__isnull=True, assigned_departments__isnull=True) | Q(assigned_users=request.user)
        if profile and profile.department_id:
            eligible |= Q(assigned_departments=profile.department_id)
        return queryset.filter(eligible).distinct()

    @action(detail=False, methods=('get',), url_path='available')
    def available(self, request):
        return Response(self.offer_serializer_class(self.eligible_offers(request), many=True).data)

    @action(detail=False, methods=('get',), url_path='my-jobs')
    def my_jobs(self, request):
        jobs = self.get_queryset().filter(accepted_by=request.user)
        return Response(self.get_serializer(jobs, many=True).data)

    @action(detail=True, methods=('post',), url_path='accept')
    def accept(self, request, pk=None):
        job = self.get_object()
        if not self.eligible_offers(request).filter(pk=job.pk).exists():
            return Response({'detail': 'This job is no longer available to you.'}, status=status.HTTP_409_CONFLICT)
        with transaction.atomic():
            now = timezone.now()
            claimed = type(job).objects.filter(
                pk=job.pk, accepted_by__isnull=True,
                **{f'{self.status_field}__in': self.offer_statuses},
            ).update(accepted_by=request.user, accepted_at=now, updated_at=now)
            if not claimed:
                return Response({'detail': 'Another team member has already accepted this job.'}, status=status.HTTP_409_CONFLICT)
            job.assigned_users.add(request.user)
        job.refresh_from_db()
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=('post',), url_path='start')
    def start(self, request, pk=None):
        job = self.get_object()
        now = timezone.now()
        started = type(job).objects.filter(
            pk=job.pk, accepted_by=request.user, work_started_at__isnull=True,
            **{f'{self.status_field}__in': self.offer_statuses},
        ).update(work_started_at=now, updated_at=now, **{self.status_field: 'in_progress'})
        if not started:
            return Response({'detail': 'Only the person who accepted an unstarted job can start it.'}, status=status.HTTP_409_CONFLICT)
        job.refresh_from_db()
        return Response(self.get_serializer(job).data)


class InJobViewSet(JobClaimMixin, SearchableModelViewSet):
    offer_statuses = (InJob.ProductionStatus.PENDING,)
    status_field = 'printing_status'
    offer_serializer_class = InJobOfferSerializer
    queryset = InJob.objects.select_related('pipeline_job', 'customer', 'stock_item', 'printer', 'designer', 'machine', 'created_by', 'accepted_by', 'delivery', 'priority_option', 'side_option', 'payment_option').prefetch_related('assigned_users', 'assigned_departments', 'payments')
    serializer_class = InJobSerializer
    search_fields = ('job_number', 'customer_name', 'contact_number', 'job_type', 'file_name', 'invoice_no', 'designer__username', 'machine__name')

    @action(detail=False, methods=('get',), url_path='create-options')
    def create_options(self, request):
        users = [
            {
                'id': user.pk, 'username': user.username, 'first_name': user.first_name,
                'last_name': user.last_name,
                'department': getattr(getattr(user, 'libin_profile', None), 'department_id', None),
                'department_name': getattr(getattr(getattr(user, 'libin_profile', None), 'department', None), 'name', ''),
            }
            for user in get_user_model().objects.filter(is_active=True).order_by('username')
            if user_has_module_access(user, 'injobs') and user_has_module_access(user, 'jobboard')
        ]
        pipelines = []
        if user_has_module_access(request.user, 'pipeline'):
            pipelines = list(PipelineJob.objects.exclude(status__in=(
                PipelineJob.Status.CONVERTED_IN, PipelineJob.Status.CONVERTED_OUT, PipelineJob.Status.CANCELLED,
            )).filter(in_job__isnull=True, out_job__isnull=True).values(
                'id', 'job_number', 'client_name', 'contact_number', 'job_date',
                'job_type', 'quantity', 'priority', 'customer',
            ))
        job_types = sorted(set(PipelineJob.objects.exclude(job_type='').values_list('job_type', flat=True)) |
                           set(InJob.objects.exclude(job_type='').values_list('job_type', flat=True)) |
                           set(InJobDropdownOption.objects.filter(field_name='job_type', is_active=True).values_list('label', flat=True)))
        return Response({
            'customers': list(Customer.active.values('id', 'name', 'mobile')),
            'stock_items': list(StockItem.active.values('id', 'name', 'category', 'gsm', 'size', 'color')),
            'machines': list(Machine.active.values('id', 'name', 'is_default')),
            'users': users,
            'departments': list(Department.active.values('id', 'name')),
            'pipeline_jobs': pipelines,
            'job_types': job_types,
            'lamination_types': sorted(set(InJob.objects.exclude(lamination_type='').values_list('lamination_type', flat=True)) |
                                       set(InJobDropdownOption.objects.filter(field_name='lamination_type', is_active=True).values_list('label', flat=True))),
            'binding_methods': sorted(set(InJob.objects.exclude(binding_method='').values_list('binding_method', flat=True)) |
                                      set(InJobDropdownOption.objects.filter(field_name='binding_method', is_active=True).values_list('label', flat=True))),
            'custom_options': {field: list(InJobDropdownOption.objects.filter(field_name=field, is_active=True).values('id', 'label', 'base_value'))
                               for field in ('priority', 'side_mode', 'payment_status')},
        })

    @action(detail=False, methods=('get',), url_path='assignment-options')
    def assignment_options(self, request):
        kind = request.query_params.get('kind', 'users')
        if kind == 'departments':
            return Response(list(Department.objects.filter(is_active=True).values('id', 'name')))
        if kind == 'machines':
            return Response(list(Machine.objects.filter(is_active=True).values('id', 'name')))
        return Response(list(get_user_model().objects.filter(is_active=True).values('id', 'username', 'first_name', 'last_name')))

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, created_by=self.request.user)

    @action(detail=True, methods=('post',), url_path='cancel')
    def cancel(self, request, pk=None):
        job = self.get_object()
        if job.printing_status == InJob.ProductionStatus.CANCELLED:
            return Response(self.get_serializer(job).data)
        if job.printing_status == InJob.ProductionStatus.COMPLETED or job.finishing_status == InJob.ProductionStatus.COMPLETED:
            return Response({'detail': 'A completed In Job cannot be cancelled.'}, status=status.HTTP_409_CONFLICT)
        job.printing_status = InJob.ProductionStatus.CANCELLED
        job.save(update_fields=('printing_status', 'updated_at'))
        return Response(self.get_serializer(job).data)

    def get_queryset(self):
        queryset = super().get_queryset()
        for parameter in ('priority', 'printing_status', 'finishing_status', 'payment_status'):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{parameter: value})
        return queryset

    @action(detail=False, methods=('post',), url_path='bulk-assign')
    def bulk_assign(self, request):
        if not request.user.is_superuser:
            return Response({'detail': 'Only a superadmin can bulk-assign In Jobs.'}, status=status.HTTP_403_FORBIDDEN)
        job_ids = request.data.get('job_ids', [])
        user_ids = request.data.get('user_ids', [])
        if not isinstance(job_ids, list) or not job_ids or not isinstance(user_ids, list) or not user_ids:
            return Response({'detail': 'Select at least one job and one employee.'}, status=status.HTTP_400_BAD_REQUEST)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (*job_ids, *user_ids)):
            return Response({'detail': 'Job and employee IDs must be integers.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(job_ids) > 100:
            return Response({'detail': 'Bulk assignment is limited to 100 jobs at a time.'}, status=status.HTTP_400_BAD_REQUEST)
        jobs = list(InJob.objects.filter(pk__in=job_ids, accepted_by__isnull=True, printing_status=InJob.ProductionStatus.PENDING))
        if len(jobs) != len(set(job_ids)):
            return Response({'detail': 'Every selected job must still be an unaccepted pending job.'}, status=status.HTTP_409_CONFLICT)
        users = list(get_user_model().objects.filter(pk__in=user_ids, is_active=True))
        if len(users) != len(set(user_ids)) or any(
            not user_has_module_access(user, 'injobs') or not user_has_module_access(user, 'jobboard')
            for user in users
        ):
            return Response({'detail': 'Select active employees with In Jobs and Job Board access.'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            for job in jobs:
                job.assigned_users.add(*users)
        return Response({'assigned_jobs': len(jobs), 'assigned_users': len(users)})


class OutJobViewSet(JobClaimMixin, SearchableModelViewSet):
    offer_statuses = (OutJob.Status.PENDING, OutJob.Status.SENT)
    status_field = 'status'
    offer_serializer_class = OutJobOfferSerializer
    queryset = OutJob.objects.select_related('pipeline_job', 'customer', 'created_by', 'accepted_by', 'delivery').prefetch_related('assigned_users', 'assigned_departments', 'payments')
    serializer_class = OutJobSerializer
    search_fields = ('job_number', 'customer_name', 'contact_number', 'vendor', 'job_type', 'invoice_no')

    @action(detail=False, methods=('get',), url_path='create-options')
    def create_options(self, request):
        users = [
            {'id': user.pk, 'username': user.username, 'first_name': user.first_name, 'last_name': user.last_name}
            for user in get_user_model().objects.filter(is_active=True).order_by('username')
            if user_has_module_access(user, 'outjobs') and user_has_module_access(user, 'jobboard')
        ]
        return Response({
            'suppliers': list(Supplier.objects.filter(is_active=True).values('id', 'name')),
            'customers': list(Customer.active.values('id', 'name', 'mobile')),
            'users': users,
            'departments': list(Department.active.values('id', 'name')),
        })

    @action(detail=False, methods=('get',), url_path='assignment-options')
    def assignment_options(self, request):
        kind = request.query_params.get('kind', 'users')
        if kind == 'departments':
            return Response(list(Department.objects.filter(is_active=True).values('id', 'name')))
        return Response(list(get_user_model().objects.filter(is_active=True).values('id', 'username', 'first_name', 'last_name')))

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, created_by=self.request.user)

    @action(detail=True, methods=('post',), url_path='cancel')
    def cancel(self, request, pk=None):
        job = self.get_object()
        if job.status == OutJob.Status.CANCELLED:
            return Response(self.get_serializer(job).data)
        if job.status == OutJob.Status.COMPLETED:
            return Response({'detail': 'A completed Out Job cannot be cancelled.'}, status=status.HTTP_409_CONFLICT)
        job.status = OutJob.Status.CANCELLED
        job.save(update_fields=('status', 'updated_at'))
        return Response(self.get_serializer(job).data)

    def get_queryset(self):
        queryset = super().get_queryset()
        for parameter in ('status', 'priority', 'payment_status', 'vendor_payment_status'):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{parameter: value})
        return queryset


class JobDocumentViewSet(SearchableModelViewSet):
    queryset = JobDocument.objects.select_related('pipeline_job', 'in_job', 'out_job', 'uploaded_by')
    serializer_class = JobDocumentSerializer
    search_fields = ('original_name', 'kind')

    def perform_create(self, serializer):
        uploaded = self.request.FILES.get('file')
        serializer.save(uploaded_by=self.request.user, original_name=uploaded.name if uploaded else '')

    @action(detail=True, methods=('get',), url_path='download')
    def download(self, request, pk=None):
        document = self.get_object()
        try:
            stored_file = document.file.open('rb')
        except FileNotFoundError as exc:
            raise Http404('The document is unavailable.') from exc
        return FileResponse(stored_file, as_attachment=True, filename=document.original_name or None)

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            pipeline_filter = Q(pipeline_job__isnull=False) if user_has_module_access(self.request.user, 'pipeline') else Q(pk__in=[])
            in_filter = Q(in_job__accepted_by=self.request.user) if user_has_module_access(self.request.user, 'injobs') else Q(pk__in=[])
            out_filter = Q(out_job__accepted_by=self.request.user) if user_has_module_access(self.request.user, 'outjobs') else Q(pk__in=[])
            queryset = queryset.filter(
                pipeline_filter | in_filter | out_filter
            )
        for parameter in ('pipeline_job', 'in_job', 'out_job', 'kind'):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{parameter: value})
        return queryset


class DeliveryViewSet(SearchableModelViewSet):
    queryset = Delivery.objects.select_related('in_job', 'out_job', 'created_by')
    serializer_class = DeliverySerializer
    search_fields = ('in_job__job_number', 'out_job__job_number', 'contact_person', 'contact_number', 'transport_company')

    def perform_create(self, serializer):
        delivery = save_with_branch(serializer, self.request, created_by=self.request.user)
        if delivery.status == Delivery.Status.DELIVERED:
            try:
                auto_generate_invoice(delivery, self.request.user)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Invoice auto-generation failed for delivery %s', delivery.pk)

    def perform_update(self, serializer):
        """Auto-generate invoice when delivery status transitions to DELIVERED."""
        previous_status = self.get_object().status
        delivery = serializer.save()
        if delivery.status == Delivery.Status.DELIVERED and previous_status != Delivery.Status.DELIVERED:
            try:
                auto_generate_invoice(delivery, self.request.user)
            except Exception:
                # Invoice generation failure should not roll back delivery update
                import logging
                logging.getLogger(__name__).exception('Invoice auto-generation failed for delivery %s', delivery.pk)

    def get_queryset(self):
        queryset = super().get_queryset()
        for parameter in ('status', 'in_job', 'out_job'):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{parameter: value})
        return queryset


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.select_related('stock_item', 'in_job', 'out_job', 'created_by')
    serializer_class = StockMovementSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        for parameter in ('stock_item', 'movement_type', 'in_job', 'out_job'):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{parameter: value})
        return queryset


class MachineCounterViewSet(SearchableModelViewSet):
    queryset = MachineCounter.objects.select_related('machine', 'operator')
    serializer_class = MachineCounterSerializer
    search_fields = ('machine__code', 'machine__name', 'operator__username')

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, operator=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset()
        machine = self.request.query_params.get('machine')
        return queryset.filter(machine_id=machine) if machine else queryset

    @action(detail=False, methods=('get',), url_path='daily')
    def daily(self, request):
        count_date = parse_date(request.query_params.get('date', '')) or timezone.localdate()
        counters = {
            counter.machine_id: counter
            for counter in MachineCounter.objects.filter(count_date=count_date).select_related('machine', 'operator')
        }
        previous_counters = {}
        for counter in MachineCounter.objects.filter(
            machine__is_active=True, count_date__lt=count_date,
        ).order_by('machine_id', '-count_date').only('machine_id', 'ending_count'):
            previous_counters.setdefault(counter.machine_id, counter)
        latest_status = {}
        for item in MachineStatusHistory.objects.filter(machine__is_active=True).order_by('machine_id', '-created_at'):
            latest_status.setdefault(item.machine_id, item.created_at)
        booked = dict(InJob.objects.filter(job_date=count_date, machine__isnull=False)
                      .values_list('machine_id').annotate(total=Sum('click_count')))
        rows = []
        for machine in Machine.objects.filter(is_active=True).order_by('name'):
            counter = counters.get(machine.pk)
            actual = counter.actual_clicks if counter else None
            job_clicks = booked.get(machine.pk, 0)
            rows.append({
                'machine_id': machine.pk,
                'machine_name': machine.name,
                'machine_code': machine.code,
                'location': machine.location,
                'operational_status': machine.operational_status,
                'status_reason': machine.status_reason,
                'last_changed': latest_status.get(machine.pk, machine.updated_at),
                'counter_id': counter.pk if counter else None,
                'morning_count': counter.morning_count if counter else (
                    previous_counters[machine.pk].ending_count if machine.pk in previous_counters else None
                ),
                'ending_count': counter.ending_count if counter else None,
                'actual_clicks': actual,
                'job_clicks_booked': job_clicks,
                'difference': actual - job_clicks if actual is not None else None,
                'operator_display': counter.operator.username if counter else '',
            })
        return Response({'date': count_date, 'machines': rows})


class MachineStatusHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MachineStatusHistory.objects.select_related('machine', 'changed_by')
    serializer_class = MachineStatusHistorySerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        machine = self.request.query_params.get('machine')
        return queryset.filter(machine_id=machine) if machine else queryset


class WastageRecordViewSet(SearchableModelViewSet):
    queryset = WastageRecord.objects.select_related('machine', 'stock_item', 'in_job', 'out_job', 'recorded_by')
    serializer_class = WastageRecordSerializer
    search_fields = ('reason', 'in_job__job_number', 'out_job__job_number', 'machine__name')

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, recorded_by=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset()
        for parameter in ('wastage_type', 'machine', 'stock_item', 'in_job', 'out_job'):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{parameter: value})
        return queryset


class InvoiceViewSet(SearchableModelViewSet):
    queryset = Invoice.objects.select_related('in_job', 'out_job', 'in_job__customer', 'out_job__customer', 'created_by')
    serializer_class = InvoiceSerializer
    search_fields = (
        'invoice_no', 'in_job__job_number', 'out_job__job_number',
        'customer_name_snapshot', 'order_reference',
    )

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, created_by=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset()
        payment_status = self.request.query_params.get('payment_status')
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(invoice_date__gte=date_from)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(invoice_date__lte=date_to)
        job_type = self.request.query_params.get('job_type')
        if job_type == 'in':
            queryset = queryset.filter(in_job__isnull=False)
        elif job_type == 'out':
            queryset = queryset.filter(out_job__isnull=False)
        delivery_status = self.request.query_params.get('delivery_status')
        if delivery_status:
            queryset = queryset.filter(
                Q(in_job__delivery__status=delivery_status) | Q(out_job__delivery__status=delivery_status)
            )
        return queryset

    @action(detail=True, methods=('get',), url_path='preview-data')
    def preview_data(self, request, pk=None):
        """Return full invoice data enriched with job line items for PDF generation."""
        invoice = self.get_object()
        data = InvoiceSerializer(invoice, context={'request': request}).data
        # Build line items from job
        job = invoice.job
        items = []
        if job:
            items.append({
                'description': getattr(job, 'job_type', '') or 'Printing Service',
                'details': getattr(job, 'job_name', '') or getattr(job, 'description', '') or '',
                'quantity': getattr(job, 'quantity', 1),
                'unit_price': str(job.total_amount),
                'amount': str(job.total_amount),
            })
        data['line_items'] = items
        # Company settings for logo/signature (live URLs)
        company = CompanySettings.get_instance()
        if company:
            data['company'] = CompanySettingsSerializer(company, context={'request': request}).data
        else:
            data['company'] = None
        return Response(data)

    @action(detail=False, methods=('get',), url_path='pending-orders')
    def pending_orders(self, request):
        """List completed jobs or deliveries that do not have an invoice yet."""
        in_jobs = InJob.objects.filter(
            printing_status=InJob.ProductionStatus.COMPLETED,
            finishing_status=InJob.ProductionStatus.COMPLETED,
            invoice__isnull=True,
        ).select_related('customer')
        out_jobs = OutJob.objects.filter(
            status=OutJob.Status.COMPLETED,
            invoice__isnull=True,
        ).select_related('customer')

        results = []
        for j in in_jobs:
            deliv = getattr(j, 'delivery', None)
            results.append({
                'id': j.id,
                'kind': 'in',
                'job_number': j.job_number,
                'customer_name': j.customer_name or (j.customer.name if j.customer else ''),
                'total_amount': str(j.total_amount),
                'advance': str(j.advance),
                'delivery_status': deliv.status if deliv else 'none',
                'delivery_id': deliv.id if deliv else None,
            })
        for j in out_jobs:
            deliv = getattr(j, 'delivery', None)
            results.append({
                'id': j.id,
                'kind': 'out',
                'job_number': j.job_number,
                'customer_name': j.customer_name or (j.customer.name if j.customer else ''),
                'total_amount': str(j.total_amount),
                'advance': str(j.advance),
                'delivery_status': deliv.status if deliv else 'none',
                'delivery_id': deliv.id if deliv else None,
            })
        return Response(results)

    @action(detail=False, methods=('post',), url_path='generate-for-job')
    def generate_for_job(self, request):
        """Generate an invoice for a specific job or delivery."""
        delivery_id = request.data.get('delivery_id')
        in_job_id = request.data.get('in_job_id')
        out_job_id = request.data.get('out_job_id')

        delivery = None
        if delivery_id:
            delivery = Delivery.objects.filter(pk=delivery_id).first()
        elif in_job_id:
            job = InJob.objects.filter(pk=in_job_id).first()
            if job:
                delivery, _ = Delivery.objects.get_or_create(
                    in_job=job,
                    defaults={'created_by': request.user, 'status': Delivery.Status.DELIVERED}
                )
        elif out_job_id:
            job = OutJob.objects.filter(pk=out_job_id).first()
            if job:
                delivery, _ = Delivery.objects.get_or_create(
                    out_job=job,
                    defaults={'created_by': request.user, 'status': Delivery.Status.DELIVERED}
                )

        if not delivery:
            return Response({'error': 'Order or delivery not found.'}, status=status.HTTP_400_BAD_REQUEST)

        inv = auto_generate_invoice(delivery, request.user, force=True)
        if not inv:
            return Response({'error': 'Could not generate invoice.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(InvoiceSerializer(inv, context={'request': request}).data, status=status.HTTP_201_CREATED)


class CompanySettingsViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = CompanySettings.objects.all()
    serializer_class = CompanySettingsSerializer

    def list(self, request, *args, **kwargs):
        """Return the single company settings object or empty dict."""
        instance = CompanySettings.get_instance()
        if instance is None:
            return Response({})
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=('get',), url_path='current')
    def current(self, request):
        """Alias for list — returns current company settings."""
        return self.list(request)

    @action(detail=False, methods=('get',), permission_classes=(AllowAny,), url_path='public-branding')
    def public_branding(self, request):
        instance = CompanySettings.get_instance()
        if instance is None:
            return Response({'company_name': 'Shiva Prints', 'company_logo_url': ''})
        logo = ''
        if instance.company_logo:
            logo = request.build_absolute_uri(instance.company_logo.url)
        return Response({'company_name': instance.company_name or 'Shiva Prints', 'company_logo_url': logo})

    def create(self, request, *args, **kwargs):
        """Create company settings (only allowed if none exist yet)."""
        existing = CompanySettings.get_instance()
        if existing:
            # Redirect to update instead
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return super().create(request, *args, **kwargs)

    def get_object(self):
        """For update actions, always return the singleton."""
        instance = CompanySettings.get_instance()
        if instance is None:
            from rest_framework.exceptions import NotFound
            raise NotFound('Company settings have not been configured yet.')
        return instance


class CashAccountViewSet(SearchableModelViewSet):
    queryset = CashAccount.objects.all()
    serializer_class = CashAccountSerializer
    search_fields = ('name', 'account_type')

    def get_queryset(self):
        from .services import ensure_default_cash_accounts
        ensure_default_cash_accounts()
        return super().get_queryset()


class CustomerPaymentViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = CustomerPayment.objects.select_related('in_job', 'out_job', 'cash_account', 'recorded_by')

    def get_serializer_class(self):
        return CustomerPaymentCreateSerializer if self.action == 'create' else CustomerPaymentSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related('in_job__invoice', 'out_job__invoice')
        queryset = scope_branch_queryset(queryset, self.request.user)
        job_id = self.request.query_params.get('job')
        if job_id:
            queryset = queryset.filter(Q(in_job_id=job_id) | Q(out_job_id=job_id))
        return queryset

    @action(detail=False, methods=('get',), url_path='job-options')
    def job_options(self, request):
        jobs = [
            {
                'id': job.pk, 'kind': kind, 'job_number': job.job_number,
                'customer_name': job.customer_name, 'job_type': job.job_type,
                'balance': job.balance,
            }
            for kind, queryset in (
                ('in', scope_branch_queryset(InJob.objects.all(), request.user)), ('out', scope_branch_queryset(OutJob.objects.all(), request.user))
            )
            for job in queryset
        ]
        return Response({
            'jobs': jobs,
            'cash_accounts': list(CashAccount.objects.filter(is_active=True).values('id', 'name')),
        })

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data.copy()
        job_type = data.pop('job_type')
        job_id = data.pop('job_id')
        model = InJob if job_type == 'in' else OutJob
        try:
            job = scope_branch_queryset(model.objects.all(), request.user).get(pk=job_id)
            payment = record_customer_payment(job=job, user=request.user, **data)
        except model.DoesNotExist:
            return Response({'job_id': 'Job not found.'}, status=status.HTTP_400_BAD_REQUEST)
        except DjangoValidationError as exc:
            detail = getattr(exc, 'message_dict', None) or {'detail': exc.messages}
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(CustomerPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class VendorPaymentViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = VendorPayment.objects.select_related('out_job', 'cash_account', 'recorded_by')

    def get_serializer_class(self):
        return VendorPaymentCreateSerializer if self.action == 'create' else VendorPaymentSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related('out_job__supplier')
        queryset = scope_branch_queryset(queryset, self.request.user)
        job_id = self.request.query_params.get('job')
        return queryset.filter(out_job_id=job_id) if job_id else queryset

    @action(detail=False, methods=('get',), url_path='job-options')
    def job_options(self, request):
        return Response({
            'jobs': [
                {
                    'id': job.pk, 'kind': 'out', 'job_number': job.job_number,
                    'customer_name': job.customer_name, 'vendor': job.vendor,
                    'job_type': job.job_type, 'balance': job.vendor_balance,
                }
                for job in scope_branch_queryset(OutJob.objects.all(), request.user)
            ],
            'cash_accounts': list(CashAccount.objects.filter(is_active=True).values('id', 'name')),
        })

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.is_superuser and serializer.validated_data['out_job'].branch_id != getattr(user_branch(request.user), 'id', None):
            return Response({'out_job': 'You cannot record a payment for another branch.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            payment = record_vendor_payment(user=request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            detail = getattr(exc, 'message_dict', None) or {'detail': exc.messages}
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(VendorPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class CashTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CashTransaction.objects.select_related('account', 'customer_payment__in_job', 'customer_payment__out_job', 'vendor_payment__out_job__supplier', 'cash_transfer', 'created_by').prefetch_related('financeentry')
    serializer_class = CashTransactionSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        account = self.request.query_params.get('account')
        return queryset.filter(account_id=account) if account else queryset


class CashTransferViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = CashTransfer.objects.select_related('source', 'destination', 'created_by')

    def get_serializer_class(self):
        return CashTransferCreateSerializer if self.action == 'create' else CashTransferSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            transfer = transfer_cash(user=request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            detail = getattr(exc, 'message_dict', None) or {'detail': exc.messages}
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(CashTransferSerializer(transfer).data, status=status.HTTP_201_CREATED)


class RoleViewSet(SearchableModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    search_fields = ('name',)


class UserAccountViewSet(SearchableModelViewSet):
    queryset = get_user_model().objects.select_related('libin_profile__role', 'libin_profile__department')
    serializer_class = UserAccountSerializer
    search_fields = ('username', 'first_name', 'last_name', 'email')


class UserProfileViewSet(SearchableModelViewSet):
    queryset = UserProfile.objects.select_related('user', 'role', 'department')
    serializer_class = UserProfileSerializer
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'role__name', 'department__name')


class ModulePermissionOverrideViewSet(SearchableModelViewSet):
    queryset = ModulePermissionOverride.objects.select_related('user', 'user__libin_profile__role')
    serializer_class = ModulePermissionOverrideSerializer
    search_fields = ('user__username', 'module')

    @action(detail=False, methods=('get',), url_path='user-options')
    def user_options(self, request):
        users = get_user_model().objects.select_related('libin_profile__role').order_by('username')
        options = []
        for user in users:
            profile = getattr(user, 'libin_profile', None)
            options.append({
                'id': user.pk,
                'username': user.username,
                'full_name': user.get_full_name(),
                'is_superuser': user.is_superuser,
                'is_active': user.is_active,
                'has_profile': profile is not None,
                'profile_active': profile.is_active if profile else None,
                'show_payment_details': profile.show_payment_details if profile else True,
                'role_name': profile.role.name if profile and profile.role else None,
                'role_active': profile.role.is_active if profile and profile.role else None,
                'role_defaults': profile.role.default_permissions if profile and profile.role else None,
            })
        return Response(options)

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.query_params.get('user')
        return queryset.filter(user_id=user) if user else queryset


class FollowUpViewSet(SearchableModelViewSet):
    module_name = 'followups'
    queryset = FollowUp.objects.select_related('customer', 'assigned_to', 'created_by')
    serializer_class = FollowUpSerializer
    search_fields = ('customer_name', 'job_type', 'printing_method', 'remarks')

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, created_by=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset()
        completed = self.request.query_params.get('is_completed')
        return queryset.filter(is_completed=completed.lower() in {'1', 'true', 'yes'}) if completed is not None else queryset


class QuotationViewSet(SearchableModelViewSet):
    queryset = Quotation.objects.all()
    serializer_class = QuotationSerializer
    search_fields = ('customer_name', 'contact_number', 'notes')
    http_method_names = ('get', 'post', 'patch', 'put', 'head', 'options')

    def perform_create(self, serializer):
        save_with_branch(serializer, self.request, created_by=self.request.user)

    @action(detail=False)
    def customers(self, request):
        return Response(list(Customer.active.values('id', 'name', 'mobile', 'billing_address')))

    @action(detail=True, methods=('get',), url_path='preview-data')
    def preview_data(self, request, pk=None):
        """Return quotation data with company settings for PDF generation."""
        quotation = self.get_object()
        data = QuotationSerializer(quotation, context={'request': request}).data
        company = CompanySettings.get_instance()
        data['company'] = CompanySettingsSerializer(company, context={'request': request}).data if company else None
        return Response(data)


class SupplierViewSet(SearchableModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    search_fields = ('name', 'mobile', 'contact_person', 'services')
    # Deactivate instead of deleting supplier history.
    http_method_names = ('get', 'post', 'put', 'patch', 'head', 'options')


class FinanceEntryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = FinanceEntry.objects.select_related('account', 'supplier', 'cash_transaction')
    serializer_class = FinanceEntrySerializer

    @action(detail=False)
    def summary(self, request):
        totals = dict(FinanceEntry.objects.values('entry_type').annotate(total=Sum('amount')).values_list('entry_type', 'total'))
        return Response({
            'credit': totals.get('credit', 0), 'debit': totals.get('debit', 0), 'expense': totals.get('expense', 0),
            'accounts': list(CashAccount.objects.filter(is_active=True).values('id', 'name', 'balance')),
        })

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(Q(description__icontains=search) | Q(category__icontains=search) | Q(reference_no__icontains=search) | Q(supplier__name__icontains=search) | Q(entry_type__icontains=search))
        return queryset

    @action(detail=False, url_path='accounts')
    def accounts(self, request):
        return Response(list(CashAccount.objects.filter(is_active=True).values('id', 'name', 'balance')))

    @action(detail=False, url_path='suppliers')
    def suppliers(self, request):
        return Response(list(Supplier.objects.filter(is_active=True).values('id', 'name')))

    @action(detail=False, methods=('get',), url_path='unified-ledger')
    def unified_ledger(self, request):
        search = (request.query_params.get('search') or '').strip().lower()
        entry_type_filter = request.query_params.get('type')
        account_filter = request.query_params.get('account')

        entries = []

        # 1. Customer Payments (Credits)
        if not entry_type_filter or entry_type_filter in {'customer_payment', 'credit'}:
            cp_qs = CustomerPayment.objects.select_related(
                'in_job', 'out_job', 'cash_account', 'recorded_by'
            ).all()
            if account_filter:
                cp_qs = cp_qs.filter(cash_account_id=account_filter)
            for cp in cp_qs:
                job = cp.job
                job_num = job.job_number if job else 'Unknown'
                cust_name = job.customer_name if job else 'Unknown'
                reason = f"Receipt for {job_num} ({cust_name}) - {cp.get_payment_type_display()}"
                entries.append({
                    'id': f"cp-{cp.pk}",
                    'raw_id': cp.pk,
                    'date': str(cp.payment_date),
                    'timestamp': cp.created_at.isoformat(),
                    'type': 'Customer Payment',
                    'type_key': 'customer_payment',
                    'reason': reason,
                    'credit': float(cp.amount),
                    'debit': 0.0,
                    'account_name': cp.cash_account.name if cp.cash_account else 'Direct Advance',
                    'account_id': cp.cash_account_id,
                    'method': cp.method or 'Cash/Other',
                    'reference_no': cp.reference_no or '',
                    'recorded_by': cp.recorded_by.username if cp.recorded_by else '',
                    'job_number': job_num,
                    'customer_name': cust_name,
                })

        # 2. Vendor Payments (Debits)
        if not entry_type_filter or entry_type_filter in {'vendor_payment', 'debit'}:
            vp_qs = VendorPayment.objects.select_related(
                'out_job__supplier', 'cash_account', 'recorded_by'
            ).all()
            if account_filter:
                vp_qs = vp_qs.filter(cash_account_id=account_filter)
            for vp in vp_qs:
                job = vp.out_job
                job_num = job.job_number if job else 'Unknown'
                supp_name = job.supplier.name if job and job.supplier else (job.vendor if job else 'Unknown')
                reason = f"Supplier payment for {job_num} ({supp_name})"
                entries.append({
                    'id': f"vp-{vp.pk}",
                    'raw_id': vp.pk,
                    'date': str(vp.payment_date),
                    'timestamp': vp.created_at.isoformat(),
                    'type': 'Vendor Payment',
                    'type_key': 'vendor_payment',
                    'reason': reason,
                    'credit': 0.0,
                    'debit': float(vp.amount),
                    'account_name': vp.cash_account.name if vp.cash_account else 'Direct Settlement',
                    'account_id': vp.cash_account_id,
                    'method': vp.method or 'Cash/Other',
                    'reference_no': vp.reference_no or '',
                    'recorded_by': vp.recorded_by.username if vp.recorded_by else '',
                    'job_number': job_num,
                    'supplier_name': supp_name,
                })

        # 3. Manual Finance Entries (Credit, Debit, Expense)
        if not entry_type_filter or entry_type_filter in {'expense', 'credit', 'debit', 'manual'}:
            fe_qs = FinanceEntry.objects.select_related('account', 'supplier', 'created_by').all()
            if account_filter:
                fe_qs = fe_qs.filter(account_id=account_filter)
            if entry_type_filter and entry_type_filter in {'credit', 'debit', 'expense'}:
                fe_qs = fe_qs.filter(entry_type=entry_type_filter)
            for fe in fe_qs:
                is_credit = fe.entry_type == 'credit'
                cat_desc = f"{fe.category} · " if fe.category else ""
                reason = f"{cat_desc}{fe.description}"
                entries.append({
                    'id': f"fe-{fe.pk}",
                    'raw_id': fe.pk,
                    'date': str(fe.entry_date),
                    'timestamp': fe.created_at.isoformat(),
                    'type': fe.get_entry_type_display(),
                    'type_key': fe.entry_type,
                    'reason': reason,
                    'credit': float(fe.amount) if is_credit else 0.0,
                    'debit': 0.0 if is_credit else float(fe.amount),
                    'account_name': fe.account.name if fe.account else '',
                    'account_id': fe.account_id,
                    'method': '',
                    'reference_no': fe.reference_no or '',
                    'recorded_by': fe.created_by.username if fe.created_by else '',
                    'supplier_name': fe.supplier.name if fe.supplier else '',
                })

        # 4. Cash Transfers
        if not entry_type_filter or entry_type_filter in {'transfer'}:
            ct_qs = CashTransfer.objects.select_related('source', 'destination', 'created_by').all()
            if account_filter:
                ct_qs = ct_qs.filter(Q(source_id=account_filter) | Q(destination_id=account_filter))
            for ct in ct_qs:
                entries.append({
                    'id': f"ct-{ct.pk}",
                    'raw_id': ct.pk,
                    'date': str(ct.transfer_date),
                    'timestamp': ct.created_at.isoformat(),
                    'type': 'Cash Transfer',
                    'type_key': 'transfer',
                    'reason': f"Transfer: {ct.source.name} ➔ {ct.destination.name} ({ct.reason})",
                    'credit': 0.0,
                    'debit': float(ct.amount),
                    'account_name': f"{ct.source.name} ➔ {ct.destination.name}",
                    'account_id': ct.source_id,
                    'method': 'Internal Transfer',
                    'reference_no': '',
                    'recorded_by': ct.created_by.username if ct.created_by else '',
                })

        # Search filter
        if search:
            entries = [
                e for e in entries
                if search in e['reason'].lower()
                or search in e['type'].lower()
                or search in e['account_name'].lower()
                or search in e['reference_no'].lower()
                or search in e.get('job_number', '').lower()
                or search in e.get('customer_name', '').lower()
                or search in e.get('supplier_name', '').lower()
                or search in e['recorded_by'].lower()
            ]

        entries.sort(key=lambda x: (x['date'], x['timestamp']), reverse=True)

        total_credit = sum(e['credit'] for e in entries)
        total_debit = sum(e['debit'] for e in entries)

        from .services import ensure_default_cash_accounts
        ensure_default_cash_accounts()
        accounts = list(CashAccount.objects.filter(is_active=True).values('id', 'name', 'account_type', 'balance'))
        for acc in accounts:
            acc['balance'] = float(acc['balance'])
        total_cash = sum(a['balance'] for a in accounts)

        petty_cash = sum(a['balance'] for a in accounts if a['account_type'] == 'petty')
        bank_cash = sum(a['balance'] for a in accounts if a['account_type'] == 'net_bank')
        god_cash = sum(a['balance'] for a in accounts if a['account_type'] == 'first_payment')

        # Pending customer receivables
        in_rec = InJob.objects.exclude(printing_status=InJob.ProductionStatus.CANCELLED).exclude(payment_status='paid').aggregate(
            rec=Sum(F('total_amount') - F('advance'))
        )['rec'] or 0
        out_rec = OutJob.objects.exclude(status=OutJob.Status.CANCELLED).exclude(payment_status='paid').aggregate(
            rec=Sum(F('total_amount') - F('advance'))
        )['rec'] or 0
        total_receivables = float(in_rec + out_rec)

        # Pending vendor payables
        total_payables = float(OutJob.objects.exclude(status=OutJob.Status.CANCELLED).exclude(vendor_payment_status='paid').aggregate(
            pay=Sum(F('vendor_total_payment') - F('vendor_advance'))
        )['pay'] or 0)

        # Total job net profits
        in_prof = InJob.objects.exclude(printing_status=InJob.ProductionStatus.CANCELLED).aggregate(
            prof=Sum(F('total_amount') - F('expenses'))
        )['prof'] or 0
        out_prof = OutJob.objects.exclude(status=OutJob.Status.CANCELLED).aggregate(
            prof=Sum(F('total_amount') - F('supplier_expenses') - F('expenses'))
        )['prof'] or 0
        total_net_profit = float(in_prof + out_prof)

        return Response({
            'entries': entries,
            'summary': {
                'total_credit': total_credit,
                'total_debit': total_debit,
                'net_flow': total_credit - total_debit,
                'available_cash': total_cash,
                'petty_cash': petty_cash,
                'bank_cash': bank_cash,
                'god_cash': god_cash,
                'total_receivables': total_receivables,
                'total_payables': total_payables,
                'total_net_profit': total_net_profit,
                'accounts': accounts,
                'count': len(entries),
            }
        })

    def create(self, request):
        from .services import record_finance_entry
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            entry, created = record_finance_entry(serializer.validated_data, request.user)
        except DjangoValidationError as exc:
            return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(entry).data, status=201 if created else 200)


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        queryset = Notification.objects.filter(recipient=self.request.user)
        read = self.request.query_params.get('read')
        notification_type = self.request.query_params.get('type')
        if read is not None:
            queryset = queryset.filter(read_at__isnull=not (read.lower() in {'1', 'true', 'yes'}))
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
        return queryset

    @action(detail=True, methods=('post',), url_path='mark-read')
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=('post',), url_path='mark-all-read')
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now(), updated_at=timezone.now())
        return Response({'updated': updated})


class DashboardViewSet(viewsets.ViewSet):
    basename = 'dashboard'

    def list(self, request):
        today = timezone.localdate()
        in_jobs = scope_branch_queryset(InJob.objects.all(), request.user)
        out_jobs = scope_branch_queryset(OutJob.objects.all(), request.user)

        # Low stock details
        low_stock_qs = StockItem.objects.filter(current_stock__lte=F('min_stock'), is_active=True).order_by('current_stock')
        low_stock_count = low_stock_qs.count()
        low_stock_list = [
            {
                'id': item.pk,
                'name': str(item),
                'current_stock': float(item.current_stock),
                'min_stock': float(item.min_stock),
                'unit': item.unit,
                'category': item.category,
            }
            for item in low_stock_qs[:10]
        ]

        # Jobs requiring immediate action
        # 1. Finished production awaiting customer payment to release delivery
        in_awaiting_payment = in_jobs.filter(
            printing_status=InJob.ProductionStatus.COMPLETED,
            finishing_status=InJob.ProductionStatus.COMPLETED,
            total_amount__gt=0,
            advance__lt=F('total_amount'),
        )
        out_awaiting_payment = out_jobs.filter(
            status=OutJob.Status.COMPLETED,
            total_amount__gt=0,
            advance__lt=F('total_amount'),
        )

        # 2. Urgent priority jobs in progress/pending
        in_urgent = in_jobs.filter(priority='urgent').exclude(finishing_status__in=('completed', 'cancelled'))
        out_urgent = out_jobs.filter(priority='urgent').exclude(status__in=('completed', 'cancelled'))

        # 3. Overdue delivery jobs
        out_overdue = out_jobs.filter(delivery_date__lt=today).exclude(status__in=('completed', 'cancelled'))
        in_overdue = in_jobs.filter(delivery__delivery_date__lt=today).exclude(finishing_status__in=('completed', 'cancelled'))

        action_jobs_map = {}

        for job in in_awaiting_payment:
            action_jobs_map[f'in-{job.pk}'] = {
                'id': job.pk,
                'kind': 'in',
                'job_number': job.job_number,
                'customer_name': job.customer_name,
                'total_amount': float(job.total_amount),
                'balance': float(job.total_amount - job.advance),
                'priority': job.priority,
                'reason': 'Payment required to release delivery',
                'reason_code': 'payment_blocked',
                'date': str(job.job_date),
            }

        for job in out_awaiting_payment:
            action_jobs_map[f'out-{job.pk}'] = {
                'id': job.pk,
                'kind': 'out',
                'job_number': job.job_number,
                'customer_name': job.customer_name,
                'total_amount': float(job.total_amount),
                'balance': float(job.total_amount - job.advance),
                'priority': job.priority,
                'reason': 'Payment required to release delivery',
                'reason_code': 'payment_blocked',
                'date': str(job.delivery_date or job.created_at.date()),
            }

        for job in in_urgent:
            key = f'in-{job.pk}'
            if key not in action_jobs_map:
                action_jobs_map[key] = {
                    'id': job.pk,
                    'kind': 'in',
                    'job_number': job.job_number,
                    'customer_name': job.customer_name,
                    'total_amount': float(job.total_amount),
                    'balance': float(job.total_amount - job.advance),
                    'priority': job.priority,
                    'reason': 'Urgent priority in production',
                    'reason_code': 'urgent',
                    'date': str(job.job_date),
                }

        for job in out_urgent:
            key = f'out-{job.pk}'
            if key not in action_jobs_map:
                action_jobs_map[key] = {
                    'id': job.pk,
                    'kind': 'out',
                    'job_number': job.job_number,
                    'customer_name': job.customer_name,
                    'total_amount': float(job.total_amount),
                    'balance': float(job.total_amount - job.advance),
                    'priority': job.priority,
                    'reason': 'Urgent priority at vendor',
                    'reason_code': 'urgent',
                    'date': str(job.delivery_date or job.created_at.date()),
                }

        for job in in_overdue:
            key = f'in-{job.pk}'
            if key not in action_jobs_map:
                action_jobs_map[key] = {
                    'id': job.pk,
                    'kind': 'in',
                    'job_number': job.job_number,
                    'customer_name': job.customer_name,
                    'total_amount': float(job.total_amount),
                    'balance': float(job.total_amount - job.advance),
                    'priority': job.priority,
                    'reason': 'Overdue for delivery',
                    'reason_code': 'overdue',
                    'date': str(job.job_date),
                }

        for job in out_overdue:
            key = f'out-{job.pk}'
            if key not in action_jobs_map:
                action_jobs_map[key] = {
                    'id': job.pk,
                    'kind': 'out',
                    'job_number': job.job_number,
                    'customer_name': job.customer_name,
                    'total_amount': float(job.total_amount),
                    'balance': float(job.total_amount - job.advance),
                    'priority': job.priority,
                    'reason': 'Vendor delivery overdue',
                    'reason_code': 'overdue',
                    'date': str(job.delivery_date or job.created_at.date()),
                }

        action_required_jobs = list(action_jobs_map.values())[:10]

        # Financial & Amount data
        has_finance = (request.user.is_superuser or user_has_module_access(request.user, 'finance')) and getattr(getattr(request.user, 'libin_profile', None), 'show_payment_details', True)
        financial_data = {}
        if has_finance:
            first_of_month = today.replace(day=1)
            in_receivables = in_jobs.exclude(payment_status='paid').aggregate(
                total=Sum(F('total_amount') - F('advance'))
            )['total'] or 0
            out_receivables = out_jobs.exclude(payment_status='paid').aggregate(
                total=Sum(F('total_amount') - F('advance'))
            )['total'] or 0
            total_receivables = in_receivables + out_receivables

            vendor_payables = out_jobs.exclude(vendor_payment_status='paid').aggregate(
                total=Sum(F('vendor_total_payment') - F('vendor_advance'))
            )['total'] or 0

            month_rev_in = in_jobs.filter(job_date__gte=first_of_month, job_date__lte=today).aggregate(
                total=Sum('total_amount')
            )['total'] or 0
            month_rev_out = out_jobs.filter(created_at__date__gte=first_of_month, created_at__date__lte=today).aggregate(
                total=Sum('total_amount')
            )['total'] or 0
            month_revenue = month_rev_in + month_rev_out

            month_collected = CustomerPayment.objects.filter(
                payment_date__gte=first_of_month, payment_date__lte=today
            ).aggregate(total=Sum('amount'))['total'] or 0

            accounts = list(CashAccount.objects.filter(is_active=True).values('id', 'name', 'account_type', 'balance'))
            for acc in accounts:
                acc['balance'] = float(acc['balance'])
            avail_cash = sum(acc['balance'] for acc in accounts)

            financial_data = {
                'has_finance_access': True,
                'available_cash': float(avail_cash),
                'cash_accounts': accounts,
                'total_receivables': float(total_receivables),
                'total_payables': float(vendor_payables),
                'month_revenue': float(month_revenue),
                'month_collected': float(month_collected),
            }
        else:
            financial_data = {
                'has_finance_access': False,
                'available_cash': 0,
                'cash_accounts': [],
                'total_receivables': 0,
                'total_payables': 0,
                'month_revenue': 0,
                'month_collected': 0,
            }

        # 7-day operational and revenue trend
        trend_days = []
        for i in range(6, -1, -1):
            d = today - timezone.timedelta(days=i)
            day_in = in_jobs.filter(job_date=d)
            day_out = out_jobs.filter(created_at__date=d)
            in_cnt = day_in.count()
            out_cnt = day_out.count()
            day_rev = (day_in.aggregate(s=Sum('total_amount'))['s'] or 0) + (day_out.aggregate(s=Sum('total_amount'))['s'] or 0)
            day_col = CustomerPayment.objects.filter(payment_date=d).aggregate(s=Sum('amount'))['s'] or 0
            trend_days.append({
                'date': str(d),
                'label': d.strftime('%a %d'),
                'in_jobs': in_cnt,
                'out_jobs': out_cnt,
                'total_jobs': in_cnt + out_cnt,
                'revenue': float(day_rev) if has_finance else 0,
                'collected': float(day_col) if has_finance else 0,
            })

        # Job stages breakdown for visual charts
        pipeline_count = PipelineJob.objects.exclude(status__in=(PipelineJob.Status.CONVERTED_IN, PipelineJob.Status.CONVERTED_OUT, PipelineJob.Status.CANCELLED)).count()
        printing_count = in_jobs.filter(printing_status=InJob.ProductionStatus.IN_PROGRESS).count()
        finishing_count = in_jobs.filter(finishing_status=InJob.ProductionStatus.IN_PROGRESS).count()
        vendor_count = out_jobs.filter(status__in=(OutJob.Status.PENDING, OutJob.Status.SENT, OutJob.Status.IN_PROGRESS, OutJob.Status.READY)).count()
        completed_count = in_jobs.filter(finishing_status=InJob.ProductionStatus.COMPLETED).count() + out_jobs.filter(status=OutJob.Status.COMPLETED).count()

        stages_breakdown = [
            {'id': 0, 'value': pipeline_count, 'label': 'Pipeline', 'color': '#7c3aed'},
            {'id': 1, 'value': printing_count, 'label': 'Printing', 'color': '#167d89'},
            {'id': 2, 'value': finishing_count, 'label': 'Finishing', 'color': '#e67e22'},
            {'id': 3, 'value': vendor_count, 'label': 'Vendor Out', 'color': '#2563eb'},
            {'id': 4, 'value': completed_count, 'label': 'Completed', 'color': '#2f8f63'},
        ]

        data = {
            'total_jobs': in_jobs.count() + out_jobs.count(),
            'pipeline': pipeline_count,
            'printing': printing_count,
            'completed': completed_count,
            'delivered': scope_branch_queryset(Delivery.objects.filter(status=Delivery.Status.DELIVERED), request.user).count(),
            'pending_payments': in_jobs.exclude(payment_status='paid').count() + out_jobs.exclude(payment_status='paid').count(),
            'low_stock_items': low_stock_count,
            'low_stock_list': low_stock_list,
            'action_required_jobs': action_required_jobs,
            'action_required_count': len(action_jobs_map),
            'trend_days': trend_days,
            'stages_breakdown': stages_breakdown,
            'today_machine_clicks': 0,
            'today_wastage': WastageRecord.objects.filter(wastage_date=today).aggregate(total=Sum('quantity'))['total'] or 0,
            'urgent_jobs': in_jobs.filter(priority='urgent').count() + out_jobs.filter(priority='urgent').count(),
            'unread_notifications': Notification.objects.filter(recipient=request.user, read_at__isnull=True).count(),
            **financial_data,
        }
        return Response(data)


class ReportViewSet(viewsets.ViewSet):
    basename = 'report'

    def list(self, request):
        return Response({'reports': ['daily', 'monthly', 'production', 'user-performance', 'machine-usage', 'stock', 'customers', 'out-jobs', 'deliveries', 'pending', 'wastage', 'finance', 'cash']})

    def _range(self, request):
        start = request.query_params.get('from')
        end = request.query_params.get('to')
        return start, end

    def _scope(self, queryset, request):
        return scope_branch_queryset(queryset, request.user)

    @action(detail=False, methods=('get',))
    def daily(self, request):
        day = request.query_params.get('date', str(timezone.localdate()))
        in_qs, out_qs = self._scope(InJob.objects.filter(job_date=day), request), self._scope(OutJob.objects.filter(created_at__date=day), request)
        return Response({'date': day, 'in_jobs': in_qs.count(), 'out_jobs': out_qs.count(), 'revenue': (in_qs.aggregate(v=Sum('total_amount'))['v'] or 0) + (out_qs.aggregate(v=Sum('total_amount'))['v'] or 0)})

    @action(detail=False, methods=('get',))
    def monthly(self, request):
        month = request.query_params.get('month', timezone.localdate().strftime('%Y-%m'))
        year, month_number = map(int, month.split('-'))
        in_qs = self._scope(InJob.objects.filter(job_date__year=year, job_date__month=month_number), request)
        out_qs = self._scope(OutJob.objects.filter(created_at__year=year, created_at__month=month_number), request)
        return Response({'month': month, 'jobs': in_qs.count() + out_qs.count(), 'revenue': (in_qs.aggregate(v=Sum('total_amount'))['v'] or 0) + (out_qs.aggregate(v=Sum('total_amount'))['v'] or 0)})

    @action(detail=False, methods=('get',))
    def production(self, request):
        start, end = self._range(request)
        queryset = self._scope(InJob.objects.all(), request)
        if start: queryset = queryset.filter(job_date__gte=start)
        if end: queryset = queryset.filter(job_date__lte=end)
        return Response({'jobs': queryset.count(), 'sheets': queryset.aggregate(v=Sum('sheet_count'))['v'] or 0, 'clicks': queryset.aggregate(v=Sum('click_count'))['v'] or 0, 'value': queryset.aggregate(v=Sum('total_amount'))['v'] or 0})

    @action(detail=False, methods=('get',), url_path='user-performance')
    def user_performance(self, request):
        rows = get_user_model().objects.annotate(in_jobs=Count('assigned_in_jobs', distinct=True), out_jobs=Count('assigned_out_jobs', distinct=True)).values('id', 'username', 'first_name', 'last_name', 'in_jobs', 'out_jobs')
        return Response(list(rows))

    @action(detail=False, methods=('get',), url_path='machine-usage')
    def machine_usage(self, request):
        start, end = self._range(request)
        queryset = self._scope(MachineCounter.objects.select_related('machine', 'operator'), request)
        if start: queryset = queryset.filter(count_date__gte=start)
        if end: queryset = queryset.filter(count_date__lte=end)
        return Response(MachineCounterSerializer(queryset, many=True).data)

    @action(detail=False, methods=('get',))
    def stock(self, request):
        return Response({'items': StockItemSerializer(StockItem.objects.all(), many=True).data, 'low_stock_count': StockItem.objects.filter(current_stock__lte=F('min_stock')).count()})

    @action(detail=False, methods=('get',))
    def customers(self, request):
        rows = [{'id': customer.id, 'name': customer.name, 'in_jobs': customer.in_jobs.count(), 'out_jobs': customer.out_jobs.count(), 'total_amount': (customer.in_jobs.aggregate(v=Sum('total_amount'))['v'] or 0) + (customer.out_jobs.aggregate(v=Sum('total_amount'))['v'] or 0)} for customer in Customer.objects.all()]
        return Response(rows)

    @action(detail=False, methods=('get',), url_path='out-jobs')
    def out_jobs(self, request):
        queryset = OutJob.objects.all() if request.user.is_superuser else OutJob.objects.filter(accepted_by=request.user)
        return Response(OutJobSerializer(queryset, many=True, context={'request': request}).data)

    @action(detail=False, methods=('get',))
    def deliveries(self, request):
        return Response(DeliverySerializer(Delivery.objects.all(), many=True).data)

    @action(detail=False, methods=('get',))
    def pending(self, request):
        in_jobs = InJob.objects.all() if request.user.is_superuser else InJob.objects.filter(accepted_by=request.user)
        out_jobs = OutJob.objects.all() if request.user.is_superuser else OutJob.objects.filter(accepted_by=request.user)
        return Response({
            'in_jobs': InJobSerializer(in_jobs.exclude(finishing_status='completed'), many=True, context={'request': request}).data,
            'out_jobs': OutJobSerializer(out_jobs.exclude(status='completed'), many=True, context={'request': request}).data,
        })

    @action(detail=False, methods=('get',))
    def wastage(self, request):
        start, end = self._range(request)
        queryset = WastageRecord.objects.all()
        if start: queryset = queryset.filter(wastage_date__gte=start)
        if end: queryset = queryset.filter(wastage_date__lte=end)
        return Response(WastageRecordSerializer(queryset, many=True).data)

    @action(detail=False, methods=('get',))
    def finance(self, request):
        return Response({'customer_payments': CustomerPayment.objects.aggregate(total=Sum('amount'))['total'] or 0, 'vendor_payments': VendorPayment.objects.aggregate(total=Sum('amount'))['total'] or 0})

    @action(detail=False, methods=('get',))
    def cash(self, request):
        return Response({'accounts': CashAccountSerializer(CashAccount.objects.all(), many=True).data, 'transactions': CashTransactionSerializer(CashTransaction.objects.all()[:100], many=True).data})

    @action(detail=False, methods=('get',), url_path='comprehensive')
    def comprehensive(self, request):
        start, end = self._range(request)
        profile = getattr(request.user, 'userprofile', None)
        can_show_payments = request.user.is_superuser or (profile and profile.show_payment_details)

        in_qs = self._scope(InJob.objects.select_related('customer', 'machine', 'accepted_by').all(), request)
        out_qs = self._scope(OutJob.objects.select_related('customer', 'supplier', 'accepted_by').all(), request)
        cust_pay_qs = self._scope(CustomerPayment.objects.select_related('in_job', 'out_job').all(), request)
        vend_pay_qs = self._scope(VendorPayment.objects.select_related('out_job').all(), request)
        deliv_qs = self._scope(Delivery.objects.select_related('in_job', 'out_job').all(), request)
        wastage_qs = self._scope(WastageRecord.objects.select_related('in_job', 'out_job', 'machine').all(), request)
        counters_qs = self._scope(MachineCounter.objects.select_related('machine', 'operator').all(), request)

        if not request.user.is_superuser:
            in_qs = in_qs.filter(Q(accepted_by=request.user) | Q(accepted_by__isnull=True))
            out_qs = out_qs.filter(Q(accepted_by=request.user) | Q(accepted_by__isnull=True))

        if start:
            in_qs = in_qs.filter(job_date__gte=start)
            out_qs = out_qs.filter(created_at__date__gte=start)
            cust_pay_qs = cust_pay_qs.filter(payment_date__gte=start)
            vend_pay_qs = vend_pay_qs.filter(payment_date__gte=start)
            deliv_qs = deliv_qs.filter(delivery_date__gte=start)
            wastage_qs = wastage_qs.filter(wastage_date__gte=start)
            counters_qs = counters_qs.filter(count_date__gte=start)

        if end:
            in_qs = in_qs.filter(job_date__lte=end)
            out_qs = out_qs.filter(created_at__date__lte=end)
            cust_pay_qs = cust_pay_qs.filter(payment_date__lte=end)
            vend_pay_qs = vend_pay_qs.filter(payment_date__lte=end)
            deliv_qs = deliv_qs.filter(delivery_date__lte=end)
            wastage_qs = wastage_qs.filter(wastage_date__lte=end)
            counters_qs = counters_qs.filter(count_date__lte=end)

        total_in_revenue = in_qs.aggregate(v=Sum('total_amount'))['v'] or 0
        total_out_revenue = out_qs.aggregate(v=Sum('total_amount'))['v'] or 0
        total_revenue = total_in_revenue + total_out_revenue

        total_customer_collected = cust_pay_qs.aggregate(v=Sum('amount'))['v'] or 0
        total_vendor_cost = out_qs.aggregate(v=Sum('vendor_total_payment'))['v'] or 0
        total_vendor_paid = vend_pay_qs.aggregate(v=Sum('amount'))['v'] or 0

        in_pending_bal = in_qs.aggregate(v=Sum(F('total_amount') - F('advance')))['v'] or 0
        out_pending_bal = out_qs.aggregate(v=Sum(F('total_amount') - F('advance')))['v'] or 0
        total_customer_pending = in_pending_bal + out_pending_bal
        out_vendor_pending = out_qs.aggregate(v=Sum(F('vendor_total_payment') - F('vendor_advance')))['v'] or 0
        gross_profit = total_revenue - total_vendor_cost

        total_sheets = in_qs.aggregate(v=Sum('sheet_count'))['v'] or 0
        total_clicks = in_qs.aggregate(v=Sum('click_count'))['v'] or 0
        total_wastage_qty = wastage_qs.aggregate(v=Sum('quantity'))['v'] or 0

        in_jobs_data = []
        for j in in_qs.order_by('-job_date', '-id')[:250]:
            in_jobs_data.append({
                'id': j.id,
                'job_number': j.job_number or f'IJ-{j.id}',
                'job_name': j.job_name or j.job_type or '—',
                'customer_name': j.customer.name if j.customer else (j.customer_name or '—'),
                'job_type': j.job_type or '—',
                'job_date': str(j.job_date) if j.job_date else '—',
                'priority': j.priority,
                'printing_status': j.printing_status,
                'finishing_status': j.finishing_status,
                'sheet_count': j.sheet_count,
                'click_count': j.click_count,
                'total_amount': float(j.total_amount) if can_show_payments else None,
                'advance': float(j.advance) if can_show_payments else None,
                'balance': float(j.balance) if can_show_payments else None,
                'payment_status': j.payment_status if can_show_payments else None,
            })

        out_jobs_data = []
        for j in out_qs.order_by('-created_at', '-id')[:250]:
            out_jobs_data.append({
                'id': j.id,
                'job_number': j.job_number or f'OJ-{j.id}',
                'job_name': j.description or j.job_type or '—',
                'customer_name': j.customer.name if j.customer else (j.customer_name or '—'),
                'vendor_name': j.supplier.name if j.supplier else (j.vendor or '—'),
                'created_at': j.created_at.strftime('%Y-%m-%d') if j.created_at else '—',
                'delivery_date': str(j.delivery_date) if j.delivery_date else '—',
                'priority': j.priority,
                'status': j.status,
                'quantity': j.quantity,
                'total_amount': float(j.total_amount) if can_show_payments else None,
                'vendor_cost': float(j.vendor_total_payment) if can_show_payments else None,
                'vendor_total_payment': float(j.vendor_total_payment) if can_show_payments else None,
                'profit': float(j.profit) if can_show_payments else None,
                'payment_status': j.payment_status if can_show_payments else None,
                'vendor_payment_status': j.vendor_payment_status if can_show_payments else None,
            })

        customer_payments_data = []
        if can_show_payments:
            for p in cust_pay_qs.order_by('-payment_date', '-id')[:250]:
                job_ref = p.in_job.job_number if p.in_job else (p.out_job.job_number if p.out_job else '—')
                c_name = p.in_job.customer_name if p.in_job else (p.out_job.customer_name if p.out_job else '—')
                customer_payments_data.append({
                    'id': p.id,
                    'payment_number': f'RCP-{p.id}',
                    'customer_name': c_name,
                    'job_number': job_ref,
                    'job_type': p.payment_type,
                    'amount': float(p.amount),
                    'payment_method': p.method or 'Cash',
                    'payment_date': str(p.payment_date),
                    'reference': p.reference_no or '',
                })

        vendor_payments_data = []
        if can_show_payments:
            for p in vend_pay_qs.order_by('-payment_date', '-id')[:250]:
                v_name = p.out_job.supplier.name if p.out_job and p.out_job.supplier else (p.out_job.vendor if p.out_job else '—')
                vendor_payments_data.append({
                    'id': p.id,
                    'payment_number': f'VND-{p.id}',
                    'supplier_name': v_name,
                    'out_job_number': p.out_job.job_number if p.out_job else '—',
                    'amount': float(p.amount),
                    'payment_method': p.method or 'Cash',
                    'payment_date': str(p.payment_date),
                    'reference': p.reference_no or '',
                })

        customers_data = []
        for c in Customer.objects.annotate(
            in_count=Count('in_jobs', distinct=True),
            out_count=Count('out_jobs', distinct=True),
        )[:200]:
            in_tot = c.in_jobs.aggregate(v=Sum('total_amount'))['v'] or 0
            out_tot = c.out_jobs.aggregate(v=Sum('total_amount'))['v'] or 0
            in_adv = c.in_jobs.aggregate(v=Sum('advance'))['v'] or 0
            out_adv = c.out_jobs.aggregate(v=Sum('advance'))['v'] or 0
            tot_b = in_tot + out_tot
            tot_adv = in_adv + out_adv
            out_bal = tot_b - tot_adv
            customers_data.append({
                'id': c.id,
                'name': c.name,
                'mobile': c.mobile or '—',
                'total_jobs': c.in_count + c.out_count,
                'total_billed': float(tot_b) if can_show_payments else None,
                'total_paid': float(tot_adv) if can_show_payments else None,
                'outstanding_balance': float(out_bal) if can_show_payments else None,
            })

        deliveries_data = []
        for d in deliv_qs.order_by('-delivery_date', '-id')[:200]:
            job_num = d.in_job.job_number if d.in_job else (d.out_job.job_number if d.out_job else '—')
            cust_name = d.in_job.customer_name if d.in_job else (d.out_job.customer_name if d.out_job else '—')
            deliveries_data.append({
                'id': d.id,
                'job_number': job_num,
                'customer_name': cust_name,
                'delivery_address': d.address or '—',
                'delivery_method': d.method or '—',
                'status': d.status,
                'delivery_charges': float(d.delivery_charges) if can_show_payments else None,
                'delivery_date': str(d.delivery_date) if d.delivery_date else '—',
                'driver_notes': d.instructions or '',
            })

        stock_data = []
        for s in StockItem.objects.all():
            stock_data.append({
                'id': s.id,
                'name': s.name,
                'category': s.category,
                'unit': s.unit,
                'current_stock': s.current_stock,
                'min_stock': s.min_stock,
                'is_low_stock': s.current_stock <= s.min_stock,
            })

        wastage_data = []
        for w in wastage_qs.order_by('-wastage_date', '-id')[:200]:
            job_num = w.in_job.job_number if w.in_job else (w.out_job.job_number if w.out_job else '—')
            wastage_data.append({
                'id': w.id,
                'job_number': job_num,
                'machine_name': w.machine.name if w.machine else '—',
                'wastage_date': str(w.wastage_date),
                'reason': w.reason,
                'sheets_wasted': float(w.quantity),
                'wastage_type': w.get_wastage_type_display(),
            })

        counters_data = []
        for mc in counters_qs.order_by('-count_date', '-id')[:200]:
            op_name = f"{mc.operator.first_name} {mc.operator.last_name}".strip() or mc.operator.username if mc.operator else '—'
            counters_data.append({
                'id': mc.id,
                'machine_name': mc.machine.name if mc.machine else '—',
                'operator_name': op_name,
                'count_date': str(mc.count_date),
                'closing_counter': mc.ending_count,
                'click_count': mc.actual_clicks,
                'job_clicks_booked': mc.job_clicks_booked,
            })

        cash_accounts_data = []
        if can_show_payments:
            for ca in CashAccount.objects.all():
                cash_accounts_data.append({
                    'id': ca.id,
                    'name': ca.name,
                    'account_type': ca.account_type,
                    'balance': float(ca.balance),
                })

        return Response({
            'period': {'from': start or 'All time', 'to': end or 'Present'},
            'can_show_payments': can_show_payments,
            'kpis': {
                'total_jobs': in_qs.count() + out_qs.count(),
                'in_jobs_count': in_qs.count(),
                'out_jobs_count': out_qs.count(),
                'total_revenue': float(total_revenue) if can_show_payments else 0,
                'total_customer_collected': float(total_customer_collected) if can_show_payments else 0,
                'total_customer_pending': float(total_customer_pending) if can_show_payments else 0,
                'total_vendor_cost': float(total_vendor_cost) if can_show_payments else 0,
                'total_vendor_paid': float(total_vendor_paid) if can_show_payments else 0,
                'total_vendor_pending': float(out_vendor_pending) if can_show_payments else 0,
                'gross_profit': float(gross_profit) if can_show_payments else 0,
                'total_sheets': total_sheets,
                'total_clicks': total_clicks,
                'total_wastage_sheets': float(total_wastage_qty),
                'low_stock_items': StockItem.objects.filter(current_stock__lte=F('min_stock')).count(),
            },
            'in_jobs': in_jobs_data,
            'out_jobs': out_jobs_data,
            'customer_payments': customer_payments_data,
            'vendor_payments': vendor_payments_data,
            'customers': customers_data,
            'deliveries': deliveries_data,
            'stock_items': stock_data,
            'wastage_records': wastage_data,
            'machine_counters': counters_data,
            'cash_accounts': cash_accounts_data,
        })
