from django.core.exceptions import ValidationError
from decimal import Decimal
import re

from django.db import transaction
from django.utils import timezone

from .models import (
    CashAccount, CashTransaction, CashTransfer, CustomerPayment, Machine,
    MachineStatusHistory, PaymentStatus, StockItem, StockMovement, VendorPayment,
)
from .models import Delivery, InJob, OutJob, PipelineJob


# Handles initials_customer_gsm_SS-or-DS_lamination_colour-sheetcount and variants
JOB_NAME_PATTERN = re.compile(
    r'^(?P<job_initials>[^_]+)_(?P<customer_name>[^_]+)_(?:(?P<job_type>[^_]+)_)?\s*(?P<gsm>\d+)\s*gsm\s*_'
    r'(?P<side_mode>SS|DS)_(?P<lamination_type>[^_]+)_(?P<colour_spec>.+)-(?P<sheet_count>\d+)sheet(?:\.\w+)?$',
    re.IGNORECASE,
)


def parse_in_job_name(job_name):
    if not job_name or not str(job_name).strip():
        return {}
    raw = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', str(job_name).strip())
    if '_' not in raw and '+' not in raw and ',' not in raw:
        return {}

    # Clean explanatory annotations like (for laminatin) or (sheet count)
    raw = re.sub(r'\(\s*(?:for\s+)?laminat\w*\s*\)', '', raw, flags=re.I)
    raw = re.sub(r'\(\s*sheet\s*count\s*\)', '', raw, flags=re.I)
    raw = re.sub(r'\(\s*sheets?\s*\)', '', raw, flags=re.I)

    # Protect arithmetic plus like 1+3 or 1 + 3 (also 1+7-8sheet)
    def mask_plus(m):
        return f"{m.group(1)}@@@PLUS@@@{m.group(2)}"
    masked = re.sub(r'(\d+)\s*\+\s*(\d+)', mask_plus, raw)

    # First split on explicit delimiters [_,+,]+
    parts = re.split(r'[\s_,+]*[_,+][\s_,+]*', masked)
    parts = [p.strip() for p in parts if p.strip()]

    # Further split if a part contains both text and trailing 1+3 or sheets/nos
    refined = []
    for p in parts:
        sub = re.split(r'(?<=[a-zA-Z])\s+(?=\d+@@@PLUS@@@\d+|\d+\s*sheets?|\d+\s*nos?)', p, flags=re.I)
        for s in sub:
            s_clean = s.strip()
            if s_clean:
                refined.append(s_clean.replace('@@@PLUS@@@', '+'))

    if len(refined) < 2:
        return {}

    res = {}
    res['job_initials'] = refined[0]
    res['customer_name'] = refined[1]

    remaining = refined[2:]
    unclaimed = []

    for p in remaining:
        # Quantity (e.g. 70nos)
        m_qty = re.fullmatch(r'(\d+)\s*nos?', p, re.I)
        if m_qty:
            res['quantity'] = int(m_qty.group(1))
            continue

        # Sheet count explicit (e.g. 18Sheet, 5sheets)
        m_sht = re.fullmatch(r'(\d+)\s*sheets?', p, re.I)
        if m_sht:
            res['sheet_count'] = int(m_sht.group(1))
            continue

        # Side mode (e.g. SS, DS, ss/ds, single side, double side)
        m_side = re.fullmatch(r'(SS|DS|single\s*side|double\s*side|ss/ds)', p, re.I)
        if m_side:
            val = m_side.group(1).upper()
            res['side_mode'] = 'DS' if 'DS' in val and 'SS' not in val else 'SS'
            continue

        # Combined colour and sheets: cmyk-8sheet, multi-8sheet, 4+4-8sheet
        m_col_sht = re.fullmatch(r'(cmyk|multi|multicolou?r|4\+4|4\+0|1\+1|1\+0)-(\d+)(?:sheets?)?', p, re.I)
        if m_col_sht:
            res['colour_spec'] = m_col_sht.group(1)
            res['sheet_count'] = int(m_col_sht.group(2))
            continue

        # Combined breakdown and sheet count: 1+7-8sheet
        m_bd_sht = re.fullmatch(r'(\d+)\+(\d+)-(\d+)(?:sheets?)?', p, re.I)
        if m_bd_sht:
            res['sheet_count'] = int(m_bd_sht.group(3))
            continue

        # Explicit colour keyword: cmyk, multi, 4+4, 4+0, 4+1
        m_col_only = re.fullmatch(r'(cmyk|multi|multicolou?r|4\+4|4\+0|4\+1)', p, re.I)
        if m_col_only:
            res['colour_spec'] = m_col_only.group(1).upper()
            continue

        # Sheet count expression: 1+14, 1+3, 1+17, 27+1 (number is sheet count)
        m_col = re.fullmatch(r'(\d+)\+(\d+)(?:\s*sheets?)?', p, re.I)
        if m_col:
            front = int(m_col.group(1))
            back = int(m_col.group(2))
            if 'sheet_count' not in res:
                res['sheet_count'] = front + back
            if 'side_mode' not in res:
                res['side_mode'] = 'DS' if back > 0 else 'SS'
            continue

        # Lamination
        m_lam = re.search(r'\b(matt|gloss|velvet|thermal|sparkle|bop|bopp|lami|lamination)\b', p, re.I)
        if m_lam:
            res['lamination_type'] = p
            continue

        # Combined paper type and GSM with 'gsm' (e.g. 'gold met 300gsm', 'art board 300gsm', '300gsm')
        m_gsm_in_p = re.search(r'\b(\d{2,4})\s*gsm\b', p, re.I)
        if m_gsm_in_p:
            res['gsm'] = int(m_gsm_in_p.group(1))
            remainder = re.sub(r'\b\d{2,4}\s*gsm\b', '', p, flags=re.I).strip()
            if remainder and 'paper_type' not in res:
                res['paper_type'] = remainder
            continue

        # Paper words with numbers without 'gsm' (e.g. 'gold met 300', 'art board 350')
        m_num = re.search(r'\b(\d{2,4})\b', p)
        if m_num and any(w in p.lower() for w in ('gold', 'met', 'paper', 'board', 'bond', 'vellum', 'sheet', 'art', 'kraft', 'card')):
            res['gsm'] = int(m_num.group(1))
            remainder = re.sub(r'\b\d{2,4}\b', '', p).strip()
            if remainder and 'paper_type' not in res:
                res['paper_type'] = remainder
            continue

        unclaimed.append(p)

    for p in unclaimed:
        # Check for numeric GSM in unclaimed
        if 'gsm' not in res and re.fullmatch(r'\d{2,4}', p):
            res['gsm'] = int(p)
        elif 'paper_type' not in res and any(w in p.lower() for w in ('gold', 'met', 'paper', 'board', 'bond', 'vellum', 'sheet', 'art', 'kraft', 'card', 'boardtype')):
            p_clean = re.sub(r'\bgsm\b', '', p, flags=re.I).strip()
            res['paper_type'] = p_clean or p
        elif 'paper_type' not in res and 'gsm' not in res:
            res['paper_type'] = p
        elif 'lamination_type' not in res and 'none' in p.lower():
            res['lamination_type'] = 'None'
        elif 'lamination_type' not in res and 'side_mode' in res and 'colour_spec' in res:
            res['lamination_type'] = p
        elif 'remarks' not in res:
            res['remarks'] = p

    if 'side_mode' not in res and 'colour_spec' in res:
        m_split = re.match(r'(\d+)\+(\d+)', res['colour_spec'])
        if m_split:
            back = int(m_split.group(2))
            res['side_mode'] = 'DS' if back > 0 else 'SS'

    return res


def initialize_job_finance(values, *, vendor=False):
    """Capture opening advances for posting, never store unrecorded receipts."""
    customer_advance = values.pop('advance', Decimal('0'))
    vendor_advance = values.pop('vendor_advance', Decimal('0')) if vendor else Decimal('0')
    values['payment_status'] = PaymentStatus.UNPAID
    if vendor:
        values['vendor_payment_status'] = PaymentStatus.UNPAID
    return customer_advance, vendor_advance


def ensure_default_cash_accounts():
    defaults = [
        (CashAccount.AccountType.NET_BANK, 'Cash 1 - Net Bank / UPI Cash'),
        (CashAccount.AccountType.PETTY, 'Cash 2 - Petty Cash'),
        (CashAccount.AccountType.FIRST_PAYMENT, "Cash 3 - First Payment (God's Account)"),
    ]
    for account_type, name in defaults:
        CashAccount.objects.get_or_create(account_type=account_type, defaults={'name': name, 'balance': Decimal('0')})


def resolve_cash_account_for_method(method='', allow_god_account=True):
    ensure_default_cash_accounts()
    method_str = (method or '').lower()
    if allow_god_account and any(w in method_str for w in ('god', 'first payment', 'pooja', 'hundi')):
        acc = CashAccount.objects.filter(is_active=True, account_type=CashAccount.AccountType.FIRST_PAYMENT).first()
        if acc:
            return acc
    if any(w in method_str for w in ('petty', 'cash', 'drawer', 'hand')):
        acc = CashAccount.objects.filter(is_active=True, account_type=CashAccount.AccountType.PETTY).first()
        if acc:
            return acc
    if any(w in method_str for w in ('bank', 'upi', 'online', 'neft', 'imps', 'cheque', 'card', 'gpay', 'phonepe')):
        acc = CashAccount.objects.filter(is_active=True, account_type=CashAccount.AccountType.NET_BANK).first()
        if acc:
            return acc
    return CashAccount.objects.filter(is_active=True).first()


def post_opening_advances(job, user, advances, cash_account=None, method='Opening advance', vendor_cash_account=None, vendor_method=None):
    customer_advance, vendor_advance = advances
    option = getattr(job, 'payment_option', None)
    if not cash_account:
        cash_account = resolve_cash_account_for_method(method, allow_god_account=True)
    if customer_advance:
        record_customer_payment(
            job, customer_advance, CustomerPayment.PaymentType.ADVANCE,
            getattr(job, 'job_date', timezone.localdate()), user, method=method,
            cash_account=cash_account,
        )
    if vendor_advance:
        v_method = vendor_method or method
        if not vendor_cash_account:
            vendor_cash_account = cash_account if cash_account and cash_account.account_type != CashAccount.AccountType.FIRST_PAYMENT else resolve_cash_account_for_method(v_method, allow_god_account=False)
        record_vendor_payment(
            job, vendor_advance, timezone.localdate(), user, method=v_method,
            cash_account=vendor_cash_account,
        )
    job.refresh_from_db()
    if isinstance(job, InJob):
        job.payment_option = option if option and option.base_value == job.payment_status else None
        job.save(update_fields=('payment_option',))


@transaction.atomic
def convert_pipeline_to_in_job(pipeline_job, user, **overrides):
    pipeline_job = PipelineJob.objects.select_for_update().get(pk=pipeline_job.pk)
    if pipeline_job.status in {PipelineJob.Status.CONVERTED_IN, PipelineJob.Status.CONVERTED_OUT}:
        raise ValidationError('This pipeline job has already been converted.')
    assigned_users = overrides.pop('assigned_users', [])
    department = overrides.pop('everyone_in_department', None)
    overrides.pop('click_count', None)
    overrides.pop('current_count', None)
    selected_customer = overrides.get('customer', pipeline_job.customer)
    stock = overrides.get('stock_item')
    values = {
        'pipeline_job': pipeline_job,
        'branch': pipeline_job.branch,
        'customer': selected_customer,
        'customer_name': pipeline_job.client_name,
        'contact_number': pipeline_job.contact_number,
        'job_date': pipeline_job.job_date,
        'job_type': pipeline_job.job_type,
        'quantity': pipeline_job.quantity,
        'priority': pipeline_job.priority,
        'remarks': pipeline_job.remarks,
        'gst_percent': Decimal('18.00'),
        'created_by': user,
    }
    values.update(parse_in_job_name(overrides.get('job_name', '')))
    if selected_customer:
        values.update(customer_name=selected_customer.name, contact_number=selected_customer.mobile)
    if stock:
        values.update(paper_type=stock.name, gsm=stock.gsm, paper_size=stock.size)
    values.update({key: value for key, value in overrides.items() if value is not None and value != ''})
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
    advances = initialize_job_finance(values)
    job = InJob.objects.create(**values)
    post_opening_advances(job, user, advances)
    if assigned_users:
        job.assigned_users.set(assigned_users)
    if department:
        job.assigned_departments.add(department)
    pipeline_job.status = PipelineJob.Status.CONVERTED_IN
    pipeline_job.save(update_fields=('status', 'updated_at'))
    return job


@transaction.atomic
def convert_pipeline_to_out_job(pipeline_job, user, **overrides):
    pipeline_job = PipelineJob.objects.select_for_update().get(pk=pipeline_job.pk)
    if pipeline_job.status in {PipelineJob.Status.CONVERTED_IN, PipelineJob.Status.CONVERTED_OUT}:
        raise ValidationError('This pipeline job has already been converted.')
    vendor = overrides.pop('vendor', '')
    if not vendor:
        raise ValidationError({'vendor': 'Vendor is required for an out job.'})
    assigned_users = overrides.pop('assigned_users', [])
    assigned_departments = overrides.pop('assigned_departments', [])
    selected_customer = overrides.get('customer', pipeline_job.customer)
    values = {
        'pipeline_job': pipeline_job,
        'branch': pipeline_job.branch,
        'customer': selected_customer,
        'customer_name': selected_customer.name if selected_customer else pipeline_job.client_name,
        'contact_number': pipeline_job.contact_number or None,
        'job_type': pipeline_job.job_type,
        'quantity': pipeline_job.quantity,
        'priority': pipeline_job.priority,
        'remarks': pipeline_job.remarks or None,
        'vendor': vendor,
        'created_by': user,
    }
    values.update(overrides)
    if selected_customer and 'contact_number' not in overrides:
        values['contact_number'] = selected_customer.mobile or None
    advances = initialize_job_finance(values, vendor=True)
    job = OutJob.objects.create(**values)
    post_opening_advances(job, user, advances)
    if assigned_users:
        job.assigned_users.set(assigned_users)
    if assigned_departments:
        job.assigned_departments.set(assigned_departments)
    pipeline_job.status = PipelineJob.Status.CONVERTED_OUT
    pipeline_job.save(update_fields=('status', 'updated_at'))
    return job


def handoff_completed_job_to_delivery(job, user):
    """Release completed production only after the customer balance is paid."""
    if isinstance(job, InJob):
        if job.printing_status != InJob.ProductionStatus.COMPLETED or job.finishing_status != InJob.ProductionStatus.COMPLETED:
            return None
        lookup = {'in_job': job}
        delivery_date = timezone.localdate()
    elif isinstance(job, OutJob):
        if job.status != OutJob.Status.COMPLETED:
            return None
        lookup = {'out_job': job}
        delivery_date = job.delivery_date or timezone.localdate()
    else:
        raise TypeError('Delivery handoff requires an in job or out job.')

    if job.total_amount > 0 and job.advance < job.total_amount:
        delivery = Delivery.objects.filter(**lookup).first()
        if delivery and delivery.status == Delivery.Status.READY:
            delivery.status = Delivery.Status.PENDING
            delivery.save(update_fields=('status', 'updated_at'))
        return None

    delivery, created = Delivery.objects.get_or_create(
        **lookup,
        defaults={
            'branch': job.branch,
            'status': Delivery.Status.READY,
            'delivery_date': delivery_date,
            'contact_person': job.customer_name,
            'contact_number': job.contact_number or '',
            'created_by': user,
        },
    )
    if not created and delivery.status == Delivery.Status.PENDING:
        delivery.status = Delivery.Status.READY
        delivery.save(update_fields=('status', 'updated_at'))
    return delivery


@transaction.atomic
def adjust_stock(stock_item, movement_type, quantity, reason, user, **job_links):
    stock_item = StockItem.objects.select_for_update().get(pk=stock_item.pk)
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise ValidationError({'quantity': 'Quantity must be greater than zero.'})
    if movement_type == StockMovement.MovementType.IN:
        new_balance = stock_item.current_stock + quantity
    elif movement_type in {StockMovement.MovementType.OUT, StockMovement.MovementType.WASTAGE}:
        new_balance = stock_item.current_stock - quantity
    elif movement_type == StockMovement.MovementType.ADJUSTMENT:
        new_balance = quantity
    else:
        raise ValidationError({'movement_type': 'Unsupported stock movement type.'})
    if new_balance < 0:
        raise ValidationError({'quantity': 'This movement would make stock negative.'})
    stock_item.current_stock = new_balance
    stock_item.save(update_fields=('current_stock', 'updated_at'))
    return StockMovement.objects.create(
        stock_item=stock_item,
        movement_type=movement_type,
        quantity=quantity,
        balance_after=new_balance,
        reason=reason,
        created_by=user,
        **job_links,
    )


@transaction.atomic
def change_machine_status(machine, new_status, reason, user):
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    if new_status in {Machine.OperationalStatus.STOPPED, Machine.OperationalStatus.BREAKDOWN} and not reason.strip():
        raise ValidationError({'reason': 'A reason is required when a machine is stopped or in breakdown.'})
    previous = machine.operational_status
    machine.operational_status = new_status
    machine.status_reason = reason
    machine.save(update_fields=('operational_status', 'status_reason', 'updated_at'))
    return MachineStatusHistory.objects.create(
        machine=machine,
        previous_status=previous,
        new_status=new_status,
        reason=reason,
        changed_by=user,
    )


def record_finance_entry(values, user):
    from django.db import IntegrityError
    from .models import FinanceEntry

    def existing_result():
        existing = FinanceEntry.objects.filter(request_key=values['request_key']).first()
        if existing is None:
            return None
        if existing.created_by_id != user.pk or any(getattr(existing, key) != value for key, value in values.items()):
            raise ValidationError({'request_key': 'This request key was already used for different entry details.'})
        return existing, False

    existing = existing_result()
    if existing:
        return existing
    try:
        with transaction.atomic():
            account = CashAccount.objects.select_for_update().get(pk=values['account'].pk)
            existing = existing_result()
            if existing:
                return existing
            if not account.is_active:
                raise ValidationError({'account': 'This account is inactive.'})
            cash = _post_cash(account, 'credit' if values['entry_type'] == 'credit' else 'debit',
                              values['amount'], values['description'], user, values.get('entry_date', timezone.localdate()))
            entry = FinanceEntry.objects.create(**values, cash_transaction=cash, created_by=user)
            return entry, True
    except IntegrityError:
        existing = existing_result()
        if existing:
            return existing
        raise


def _post_cash(account, transaction_type, amount, description, user, transaction_date, **links):
    account = CashAccount.objects.select_for_update().get(pk=account.pk)
    if transaction_type in {CashTransaction.TransactionType.CREDIT, CashTransaction.TransactionType.TRANSFER_IN}:
        new_balance = account.balance + amount
    else:
        new_balance = account.balance - amount
    if new_balance < 0:
        raise ValidationError({'cash_account': 'Insufficient cash balance.'})
    account.balance = new_balance
    account.save(update_fields=('balance', 'updated_at'))
    return CashTransaction.objects.create(
        account=account, transaction_type=transaction_type, amount=amount,
        balance_after=new_balance, description=description, created_by=user,
        transaction_date=transaction_date, **links,
    )


@transaction.atomic
def record_customer_payment(job, amount, payment_type, payment_date, user, method='', reference_no='', cash_account=None):
    model = type(job)
    job = model.objects.select_for_update().get(pk=job.pk)
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError({'amount': 'Amount must be greater than zero.'})
    if job.advance + amount > job.total_amount:
        raise ValidationError({'amount': 'Payment exceeds the outstanding customer balance.'})
    if not cash_account:
        cash_account = resolve_cash_account_for_method(method, allow_god_account=True)
    payment = CustomerPayment.objects.create(
        branch=job.branch,
        in_job=job if isinstance(job, InJob) else None,
        out_job=job if isinstance(job, OutJob) else None,
        amount=amount, payment_type=payment_type, payment_date=payment_date,
        method=method, reference_no=reference_no, cash_account=cash_account,
        recorded_by=user,
    )
    job.advance += amount
    job.payment_status = PaymentStatus.PAID if job.advance == job.total_amount else PaymentStatus.PARTIAL
    if isinstance(job, InJob):
        job.payment_option = None
        job.save(update_fields=('advance', 'payment_status', 'payment_option', 'updated_at'))
    else:
        job.save(update_fields=('advance', 'payment_status', 'updated_at'))
    if cash_account:
        _post_cash(
            cash_account, CashTransaction.TransactionType.CREDIT, amount,
            f'Customer payment for {job.job_number}', user, payment_date,
            customer_payment=payment,
        )
    handoff_completed_job_to_delivery(job, user)
    return payment


@transaction.atomic
def record_vendor_payment(out_job, amount, payment_date, user, method='', reference_no='', cash_account=None):
    out_job = OutJob.objects.select_for_update().get(pk=out_job.pk)
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError({'amount': 'Amount must be greater than zero.'})
    if out_job.vendor_advance + amount > out_job.vendor_total_payment:
        raise ValidationError({'amount': 'Payment exceeds the outstanding vendor balance.'})
    if not cash_account:
        cash_account = resolve_cash_account_for_method(method or 'petty', allow_god_account=False)
    payment = VendorPayment.objects.create(
        branch=out_job.branch, out_job=out_job, amount=amount, payment_date=payment_date, method=method,
        reference_no=reference_no, cash_account=cash_account, recorded_by=user,
    )
    out_job.vendor_advance += amount
    out_job.vendor_payment_status = PaymentStatus.PAID if out_job.vendor_advance == out_job.vendor_total_payment else PaymentStatus.PARTIAL
    out_job.save(update_fields=('vendor_advance', 'vendor_payment_status', 'updated_at'))
    if cash_account:
        _post_cash(
            cash_account, CashTransaction.TransactionType.DEBIT, amount,
            f'Vendor payment for {out_job.job_number}', user, payment_date,
            vendor_payment=payment,
        )
    return payment


@transaction.atomic
def transfer_cash(source, destination, amount, transfer_date, reason, user):
    amount = Decimal(amount)
    if source.pk == destination.pk:
        raise ValidationError({'destination': 'Source and destination accounts must be different.'})
    if amount <= 0:
        raise ValidationError({'amount': 'Amount must be greater than zero.'})
    locked = {account.pk: account for account in CashAccount.objects.select_for_update().filter(pk__in=(source.pk, destination.pk)).order_by('pk')}
    source = locked[source.pk]
    destination = locked[destination.pk]
    transfer = CashTransfer.objects.create(
        source=source, destination=destination, amount=amount,
        transfer_date=transfer_date, reason=reason, created_by=user,
    )
    _post_cash(source, CashTransaction.TransactionType.TRANSFER_OUT, amount, reason, user, transfer_date, cash_transfer=transfer)
    _post_cash(destination, CashTransaction.TransactionType.TRANSFER_IN, amount, reason, user, transfer_date, cash_transfer=transfer)
    return transfer


@transaction.atomic
def auto_generate_invoice(delivery, user, force=False):
    """
    Generate an invoice after a delivery is marked as DELIVERED.
    Idempotent: returns existing invoice if one already exists for the job.
    Transaction-safe: uses select_for_update to prevent duplicate creation.
    Captures immutable snapshots of company and customer details at time of generation.
    """
    from .models import CompanySettings, Invoice, Delivery, InJob, OutJob

    if not force and delivery.status != Delivery.Status.DELIVERED:
        return None

    job = delivery.job
    if job is None:
        return None

    # Determine job type and get the job locked for update
    if delivery.in_job_id:
        job = InJob.objects.select_for_update().get(pk=delivery.in_job_id)
        in_job = job
        out_job = None
    elif delivery.out_job_id:
        job = OutJob.objects.select_for_update().get(pk=delivery.out_job_id)
        in_job = None
        out_job = job
    else:
        return None

    # Idempotency check - return existing invoice if already generated
    existing = getattr(job, 'invoice', None)
    if existing is not None:
        return existing

    # Gather company settings snapshot
    company = CompanySettings.get_instance()
    request_scheme = 'http'  # Will be absolute URI from request if passed

    company_logo_url = ''
    signature_url = ''
    if company and company.company_logo:
        try:
            company_logo_url = company.company_logo.url
        except Exception:
            pass
    if company and company.digital_signature:
        try:
            signature_url = company.digital_signature.url
        except Exception:
            pass

    # Gather customer snapshot
    customer = getattr(job, 'customer', None)
    customer_name = job.customer_name or (customer.name if customer else '')
    customer_address = ''
    customer_gstin = ''
    if customer:
        customer_address = customer.billing_address or customer.address or ''
        customer_gstin = customer.gst_number or ''
    contact = getattr(job, 'contact_number', '') or ''

    # Generate invoice number (use pk-based after save, so do 2-step)
    # Determine GST percent (default to 18% standard commercial printing GST if job has 0)
    job_gst = getattr(job, 'gst_percent', Decimal('0')) or Decimal('0')
    gst_percent = job_gst if job_gst > 0 else Decimal('18.00')

    # Calculate payment status from job finances
    advance = getattr(job, 'advance', Decimal('0')) or Decimal('0')
    subtotal = job.total_amount or Decimal('0')
    if advance >= subtotal and subtotal > 0:
        inv_payment_status = 'paid'
    elif advance > 0:
        inv_payment_status = 'partial'
    else:
        inv_payment_status = getattr(job, 'payment_status', 'unpaid') or 'unpaid'

    # Build snapshot data
    invoice_kwargs = {
        'in_job': in_job,
        'out_job': out_job,
        'branch': getattr(job, 'branch', None),
        'invoice_date': timezone.localdate(),
        'subtotal': subtotal,
        'discount': Decimal('0'),
        'gst_percent': gst_percent,
        'payment_status': inv_payment_status,
        'notes': getattr(job, 'remarks', '') or '',
        'created_by': user,
        # Company snapshot
        'company_name_snapshot': company.company_name if company else '',
        'company_address_snapshot': company.address if company else '',
        'company_gstin_snapshot': company.gstin if company else '',
        'company_contact_snapshot': company.contact_number if company else '',
        'company_email_snapshot': company.email if company else '',
        'company_logo_url': company_logo_url,
        'signature_url': signature_url,
        'authorized_person_snapshot': company.authorized_person_name if company else '',
        'authorized_designation_snapshot': company.authorized_person_designation if company else '',
        'terms_snapshot': company.terms_and_conditions if company else '',
        # Customer snapshot
        'customer_name_snapshot': customer_name,
        'customer_address_snapshot': customer_address,
        'customer_gstin_snapshot': customer_gstin,
        'customer_contact_snapshot': contact,
        # Order reference
        'order_reference': job.job_number or '',
    }

    # First save without invoice_no to get the pk, then update
    invoice = Invoice.objects.create(invoice_no='TEMP', **invoice_kwargs)
    final_invoice_no = f'INV-{timezone.localdate().year}-{invoice.pk:06d}'
    Invoice.objects.filter(pk=invoice.pk).update(invoice_no=final_invoice_no)
    invoice.invoice_no = final_invoice_no
    return invoice
