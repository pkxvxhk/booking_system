from decimal import Decimal

from django.core.management.base import BaseCommand

from booking.models import Feature, Room, RoomType


class Command(BaseCommand):
    help = "Створює демонстраційні типи, особливості та кімнати/місця"

    def handle(self, *args, **options):
        types = {
            name: RoomType.objects.get_or_create(name=name, defaults={"description": desc})[0]
            for name, desc in [
                ("Переговорна", "Кімнати для зустрічей і нарад"),
                ("Конференц-зал", "Великі зали для заходів"),
                ("Робоче місце", "Окремі місця в коворкінгу"),
            ]
        }
        features = {
            name: Feature.objects.get_or_create(name=name)[0]
            for name in ["Проектор", "Wi-Fi", "Дошка", "Кондиціонер", "Відеозв'язок"]
        }
        rooms = [
            ("Переговорна A", "Переговорна", 6, "250.00", ["Wi-Fi", "Дошка"]),
            ("Переговорна B", "Переговорна", 10, "350.00", ["Wi-Fi", "Проектор", "Відеозв'язок"]),
            ("Великий зал", "Конференц-зал", 80, "1500.00", ["Wi-Fi", "Проектор", "Кондиціонер"]),
            ("Місце 1", "Робоче місце", 1, "60.00", ["Wi-Fi"]),
            ("Місце 2", "Робоче місце", 1, "60.00", ["Wi-Fi"]),
        ]
        created = 0
        for name, type_name, capacity, price, feature_names in rooms:
            room, is_new = Room.objects.get_or_create(
                name=name,
                defaults={
                    "room_type": types[type_name],
                    "capacity": capacity,
                    "price_per_hour": Decimal(price),
                },
            )
            room.features.set([features[f] for f in feature_names])
            created += int(is_new)
        self.stdout.write(self.style.SUCCESS(f"Готово. Нових кімнат/місць: {created}"))
