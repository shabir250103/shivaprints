from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied

from .models import ModulePermissionOverride, UserProfile


MODULE_BY_BASENAME = {
    'quotation': 'quotations',
    'supplier': 'suppliers', 'financeentry': 'finance', 'enquiry': 'followups',
    'pipelinejob': 'pipeline', 'injob': 'injobs', 'outjob': 'outjobs',
    'delivery': 'delivery', 'stockitem': 'stock', 'stockmovement': 'stock',
    'customer': 'customers', 'customertype': 'customers',
    'machine': 'machine', 'machinecounter': 'machine', 'machinestatushistory': 'machine',
    'cashaccount': 'cash', 'cashtransaction': 'cash', 'cashtransfer': 'cash',
    'wastagerecord': 'wastage', 'customerpayment': 'finance', 'vendorpayment': 'finance',
    'invoice': 'accounts', 'notification': 'notifications', 'followup': 'followups',
    'useraccount': 'users', 'role': 'users', 'userprofile': 'users',
    'department': 'users',
    'branch': 'users',
    'modulepermissionoverride': 'permissions', 'dashboard': 'dashboard', 'report': 'reports',
    'companysettings': 'company_settings',
}


def user_has_module_access(user, module):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    try:
        profile = user.libin_profile
    except UserProfile.DoesNotExist:
        return False
    if not profile.is_active or not user.is_active:
        return False
    if not profile.show_payment_details and module in ('finance', 'cash', 'accounts'):
        return False
    if profile.role and not profile.role.is_active:
        return False
    override = user.module_permission_overrides.filter(module=module).first()
    if override and override.access != ModulePermissionOverride.Access.DEFAULT:
        return override.access == ModulePermissionOverride.Access.ALLOW
    if not profile.role:
        return False
    defaults = profile.role.default_permissions
    return isinstance(defaults, dict) and defaults.get(module, False) is True


def check_user_management(actor, target):
    """Delegated administrators cannot take over privileged accounts."""
    if actor.is_superuser:
        return
    if target.is_superuser or target.is_staff:
        raise PermissionDenied('Only a superadmin can manage privileged accounts.')
    profile = getattr(target, 'libin_profile', None)
    defaults = profile.role.default_permissions if profile and profile.role else {}
    grants = {module for module, allowed in defaults.items() if allowed is True} if isinstance(defaults, dict) else set()
    grants.update(target.module_permission_overrides.filter(access='allow').values_list('module', flat=True))
    # Include dormant grants: reactivation or removing a deny must not elevate access.
    if any(not user_has_module_access(actor, module) for module in grants):
        raise PermissionDenied('You cannot manage an account with permissions beyond your own.')


def check_permission_grant(actor, module, allowed):
    if allowed and not user_has_module_access(actor, module):
        raise PermissionDenied('You cannot grant a permission you do not have.')


class ModuleAccessPermission(BasePermission):
    def has_permission(self, request, view):
        basename = getattr(view, 'basename', '')
        if basename == 'invoice':
            if user_has_module_access(request.user, 'accounts') or user_has_module_access(request.user, 'delivery'):
                return True
        module = getattr(view, 'module_name', None) or MODULE_BY_BASENAME.get(basename)
        return True if not module else user_has_module_access(request.user, module)

    def has_object_permission(self, request, view, obj):
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        basename = getattr(view, 'basename', '')
        if basename == 'useraccount':
            check_user_management(request.user, obj)
        elif basename in ('userprofile', 'modulepermissionoverride'):
            check_user_management(request.user, obj.user)
            if basename == 'modulepermissionoverride' and request.method == 'DELETE':
                profile = getattr(obj.user, 'libin_profile', None)
                role = profile.role if profile else None
                check_permission_grant(request.user, obj.module, bool(role and role.default_permissions.get(obj.module)))
        elif basename == 'role' and not request.user.is_superuser:
            if obj.users.filter(user__is_superuser=True).exists() or obj.users.filter(user__is_staff=True).exists():
                raise PermissionDenied('Only a superadmin can change a privileged account role.')
        return True
