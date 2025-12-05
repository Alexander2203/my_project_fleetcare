from rest_framework import serializers
from .models import Automobile, Driver, Slot, Appointment


# Авто
class AutomobileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Automobile
        fields = [
            "id",
            "plate_number",
            "make",
            "model",
            "last_service_mileage",
            "service_interval_km",
            "next_service_mileage",
        ]


# Водитель
class DriverSerializer(serializers.ModelSerializer):
    car = AutomobileSerializer(read_only=True)
    chat_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = Driver
        fields = ["id", "first_name", "last_name", "phone", "car", "chat_id"]


# Слот
class SlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Slot
        fields = ["id", "date", "time", "status"]


# Запись
class AppointmentSerializer(serializers.ModelSerializer):
    slot = SlotSerializer(read_only=True)
    slot_id = serializers.PrimaryKeyRelatedField(
        source="slot", queryset=Slot.objects.all(), write_only=True, required=True
    )

    class Meta:
        model = Appointment
        fields = ["id", "slot", "slot_id", "driver", "car", "status", "created_at"]
