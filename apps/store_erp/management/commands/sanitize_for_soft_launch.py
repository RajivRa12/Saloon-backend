import os
import sys
from datetime import datetime
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.db import transaction
from apps.core.models import (
    Store, Outlet, Business, Brand, StoreGroup,
    ServiceCategory, Service, ServiceCategoryPhase1, CanonicalService, StoreService,
    Professional, ProfessionalAccount, ProfessionalShift, StaffAvailability,
    Role, Booking, AppointmentSlot, SlotHold, QueueEntry, Waitlist,
    Invoice, InvoiceLine, WalletTransaction, DailyRegister,
    Review, ProfessionalReview, GlobalCustomer, CustomerProfile
)

User = get_user_model()

class Command(BaseCommand):
    help = "Safely sanitizes test data before soft launch (backs up DB, prunes test bookings/invoices/reviews, preserves real stores & staff)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute',
            action='store_true',
            default=False,
            help='Execute the cleanup. Without this flag, the command only prints a dry-run audit.'
        )
        parser.add_argument(
            '--skip-backup',
            action='store_true',
            default=False,
            help='Skip creating an automated JSON backup before cleanup.'
        )

    def handle(self, *args, **options):
        execute = options['execute']
        skip_backup = options['skip_backup']

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== NEARBYME SOFT LAUNCH DATA SANITIZATION ==="))

        # 1. Identify Protected Stores & Staff
        pilot_store = Store.objects.filter(email='manager@nearbyme.com').first()
        if not pilot_store:
            pilot_store = Store.objects.filter(name__icontains='NearbyMe Signature').first()

        # Dummy store emails identified during audit
        DUMMY_STORE_EMAILS = [
            'chdth342@gmail.coom',
            'steggsrsr23@gmail.com',
            'emaildt@gmail.com',
            'email34@gmail.com',
        ]

        dummy_stores = Store.objects.filter(email__in=DUMMY_STORE_EMAILS)
        kept_stores = Store.objects.exclude(email__in=DUMMY_STORE_EMAILS)

        # Authorized Users to keep
        staff_roles = [Role.STORE_ADMIN, Role.MASTER_ADMIN, Role.THERAPIST, Role.RECEPTIONIST]
        staff_users = User.objects.filter(role__in=staff_roles)

        # 2. Count Records
        booking_count = Booking.objects.count()
        slot_count = AppointmentSlot.objects.count()
        hold_count = SlotHold.objects.count()
        invoice_count = Invoice.objects.count()
        invoice_item_count = InvoiceLine.objects.count()
        tx_count = WalletTransaction.objects.count()
        review_count = Review.objects.count()
        prof_review_count = ProfessionalReview.objects.count()
        queue_count = QueueEntry.objects.count()
        waitlist_count = Waitlist.objects.count()
        customer_count = GlobalCustomer.objects.count()

        self.stdout.write(self.style.WARNING("\n[1] DATA CLASSIFICATION AUDIT:"))
        self.stdout.write(f"  • Stores Kept ({kept_stores.count()}): {[s.name for s in kept_stores]}")
        self.stdout.write(f"  • Stores to Remove ({dummy_stores.count()}): {[s.name for s in dummy_stores]}")
        self.stdout.write(f"  • Protected Staff & Admin Users ({staff_users.count()}): {[u.email for u in staff_users[:5]]}...")
        self.stdout.write(f"  • Active Services ({StoreService.objects.count()}): {CanonicalService.objects.count()} canonical variants")
        self.stdout.write(f"  • Active Bookable Professionals: {Professional.objects.filter(is_bookable=True).count()}")

        self.stdout.write(self.style.WARNING("\n[2] TEST TRANSACTIONS & ENTITIES TO CLEAN:"))
        self.stdout.write(f"  • Bookings: {booking_count}")
        self.stdout.write(f"  • Appointment Slots: {slot_count}")
        self.stdout.write(f"  • Slot Holds: {hold_count}")
        self.stdout.write(f"  • Invoices & Lines: {invoice_count} invoices, {invoice_item_count} items")
        self.stdout.write(f"  • Payment Transactions: {tx_count}")
        self.stdout.write(f"  • Test Customer Reviews: {review_count + prof_review_count}")
        self.stdout.write(f"  • Queue & Waitlist Entries: {queue_count + waitlist_count}")
        self.stdout.write(f"  • Test Customers: {customer_count}")

        if not execute:
            self.stdout.write(self.style.NOTICE(
                "\nℹ DRY RUN MODE: No database records were modified or deleted.\n"
                "To create a backup and execute this cleanup, run:\n"
                "  python manage.py sanitize_for_soft_launch --execute\n"
            ))
            return

        # 3. Create Automated Backup
        if not skip_backup:
            backup_dir = os.path.join(os.getcwd(), 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(backup_dir, f'backup_pre_soft_launch_{timestamp}.json')

            self.stdout.write(self.style.NOTICE(f"\n[3] CREATING DATABASE BACKUP:\n  --> Saving to {backup_file}..."))
            try:
                with open(backup_file, 'w', encoding='utf-8') as f:
                    call_command('dumpdata', '--natural-foreign', '--natural-primary', exclude=['contenttypes', 'auth.Permission'], stdout=f)
                self.stdout.write(self.style.SUCCESS(f"✔ Backup successfully created ({os.path.getsize(backup_file)} bytes)."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✖ Backup failed: {e}. Aborting sanitization for safety."))
                return

        # 4. Atomic Execution of Data Cleanup
        self.stdout.write(self.style.NOTICE("\n[4] EXECUTING CLEANUP IN ATOMIC TRANSACTION..."))
        try:
            with transaction.atomic():
                # A. Delete reviews
                Review.objects.all().delete()
                ProfessionalReview.objects.all().delete()

                # B. Delete queue and waitlist
                QueueEntry.objects.all().delete()
                Waitlist.objects.all().delete()

                # C. Delete financial test records
                WalletTransaction.objects.all().delete()
                InvoiceLine.objects.all().delete()
                Invoice.objects.all().delete()
                DailyRegister.objects.all().delete()

                # D. Delete appointment slots, holds and bookings
                AppointmentSlot.objects.all().delete()
                SlotHold.objects.all().delete()
                Booking.objects.all().delete()

                # E. Delete test customer records
                GlobalCustomer.objects.all().delete()
                CustomerProfile.objects.all().delete()
                # Remove test customer users (keep all staff/admins)
                User.objects.filter(role=Role.CUSTOMER).delete()

                # F. Remove identified dummy stores
                for ds in dummy_stores:
                    ds_name = ds.name
                    ds.delete()
                    self.stdout.write(f"  • Removed dummy store: {ds_name}")

            self.stdout.write(self.style.SUCCESS("\n🎉 CLEANUP COMPLETED SUCCESSFULLY!"))
            self.stdout.write(self.style.SUCCESS("Your database is now clean, 100% real, and ready for soft launch."))
            self.stdout.write(self.style.NOTICE(f"Active pilot store: {pilot_store.name if pilot_store else 'NearbyMe Signature Studio'}"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✖ Cleanup encountered an error: {e}. All changes were rolled back."))
            raise e
