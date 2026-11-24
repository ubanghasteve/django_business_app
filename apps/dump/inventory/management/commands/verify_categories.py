from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.inventory.models import InventoryItem, InventoryLayout, InventoryCategory

User = get_user_model()

class Command(BaseCommand):
    help = 'Verify and display actual categories in inventory data'

    def handle(self, *args, **options):
        self.stdout.write('=== Inventory Category Verification ===\n')
        
        # Get all users
        users = User.objects.all()
        
        for user in users:
            self.stdout.write(f"User: {user.username or user.email or user.id}")
            
            # Get user's layouts
            layouts = InventoryLayout.objects.filter(user=user)
            if not layouts.exists():
                self.stdout.write("  No layouts found\n")
                continue
            
            # Get default layout or first layout
            default_layout = layouts.filter(is_default=True).first() or layouts.first()
            self.stdout.write(f"  Layout: {default_layout.name}")
            
            # Get items in this layout
            items = InventoryItem.objects.filter(user=user, layout=default_layout)
            self.stdout.write(f"  Total items: {items.count()}")
            
            if items.count() == 0:
                self.stdout.write("  No items found\n")
                continue
            
            # Analyze category data
            self.stdout.write("\n  === Category Analysis ===")
            category_names = set()
            category_samples = []
            
            for item in items:
                # Check all possible category field names
                for field_name in ['category', 'Category', 'categories', 'Categories']:
                    if field_name in item.data:
                        value = item.data[field_name]
                        
                        if isinstance(value, dict) and value.get('name'):
                            category_names.add(value['name'])
                            category_samples.append({
                                'item': item.product_name,
                                'field': field_name,
                                'value': value['name']
                            })
                        elif isinstance(value, str) and value.strip():
                            category_names.add(value.strip())
                            category_samples.append({
                                'item': item.product_name,
                                'field': field_name,
                                'value': value.strip()
                            })
                        elif value:
                            category_names.add(str(value))
                            category_samples.append({
                                'item': item.product_name,
                                'field': field_name,
                                'value': str(value)
                            })
            
            self.stdout.write(f"  Unique categories found: {len(category_names)}")
            if category_names:
                self.stdout.write(f"  Category names: {', '.join(sorted(category_names))}")
            
            # Show sample data
            if category_samples:
                self.stdout.write("\n  === Sample Category Data ===")
                for sample in category_samples[:5]:  # Show first 5
                    self.stdout.write(f"    Item: {sample['item']}")
                    self.stdout.write(f"    Field: {sample['field']}")
                    self.stdout.write(f"    Value: {sample['value']}")
                    self.stdout.write("    ---")
            
            # Check InventoryCategory objects
            categories = InventoryCategory.objects.filter(user=user)
            self.stdout.write(f"\n  InventoryCategory objects: {categories.count()}")
            for category in categories:
                self.stdout.write(f"    - {category.name} (ID: {category.id})")
            
            self.stdout.write("\n" + "="*50 + "\n")
        
        self.stdout.write(
            self.style.SUCCESS('Category verification completed!')
        )
