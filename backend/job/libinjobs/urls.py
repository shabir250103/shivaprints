from rest_framework.routers import DefaultRouter
from django.urls import path

from .views import (
    BranchViewSet, CompanySettingsViewSet, SupplierViewSet, FinanceEntryViewSet, QuotationViewSet,
    CashAccountViewSet,
    CashTransactionViewSet,
    CashTransferViewSet,
    CustomerPaymentViewSet,
    CustomerTypeViewSet,
    CustomerViewSet,
    DashboardViewSet,
    DeliveryViewSet,
    DepartmentViewSet,
    FollowUpViewSet,
    InJobViewSet,
    InJobDropdownOptionViewSet,
    LoginAPIView,
    LogoutAPIView,
    CurrentUserAPIView,
    InvoiceViewSet,
    JobDocumentViewSet,
    JobBoardAcceptedSummaryAPIView,
    MachineViewSet,
    MachineCounterViewSet,
    MachineStatusHistoryViewSet,
    ModulePermissionOverrideViewSet,
    NotificationViewSet,
    OutJobViewSet,
    PipelineJobViewSet,
    ReportViewSet,
    RoleViewSet,
    StockCategoryViewSet,
    StockItemViewSet,
    StockMovementViewSet,
    WastageRecordViewSet,
    VendorPaymentViewSet,
    UserAccountViewSet,
    UserProfileViewSet,
)

app_name = 'libinjobs'

router = DefaultRouter()
router.register('branches', BranchViewSet)
router.register('quotations', QuotationViewSet)
router.register('suppliers', SupplierViewSet)
router.register('finance-entries', FinanceEntryViewSet)
router.register('enquiries', FollowUpViewSet, basename='enquiry')
router.register('departments', DepartmentViewSet)
router.register('customer-types', CustomerTypeViewSet)
router.register('customers', CustomerViewSet)
router.register('machines', MachineViewSet)
router.register('stock-categories', StockCategoryViewSet, basename='stockcategory')
router.register('stock-items', StockItemViewSet)
router.register('pipeline-jobs', PipelineJobViewSet)
router.register('in-jobs', InJobViewSet)
router.register('in-job-options', InJobDropdownOptionViewSet, basename='injobdropdownoption')
router.register('out-jobs', OutJobViewSet)
router.register('job-documents', JobDocumentViewSet)
router.register('deliveries', DeliveryViewSet)
router.register('stock-movements', StockMovementViewSet)
router.register('machine-counters', MachineCounterViewSet)
router.register('machine-status-history', MachineStatusHistoryViewSet)
router.register('wastage', WastageRecordViewSet)
router.register('invoices', InvoiceViewSet)
router.register('cash-accounts', CashAccountViewSet)
router.register('customer-payments', CustomerPaymentViewSet)
router.register('vendor-payments', VendorPaymentViewSet)
router.register('cash-transactions', CashTransactionViewSet)
router.register('cash-transfers', CashTransferViewSet)
router.register('roles', RoleViewSet)
router.register('users', UserAccountViewSet, basename='useraccount')
router.register('user-profiles', UserProfileViewSet)
router.register('permission-overrides', ModulePermissionOverrideViewSet)
router.register('follow-ups', FollowUpViewSet)
router.register('notifications', NotificationViewSet, basename='notification')
router.register('dashboard', DashboardViewSet, basename='dashboard')
router.register('reports', ReportViewSet, basename='report')
router.register('company-settings', CompanySettingsViewSet, basename='companysettings')

urlpatterns = [
    path('job-board/accepted-summary/', JobBoardAcceptedSummaryAPIView.as_view(), name='job-board-accepted-summary'),
    path('auth/login/', LoginAPIView.as_view(), name='auth-login'),
    path('auth/logout/', LogoutAPIView.as_view(), name='auth-logout'),
    path('auth/me/', CurrentUserAPIView.as_view(), name='auth-me'),
] + router.urls
